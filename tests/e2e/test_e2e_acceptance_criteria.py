"""
End-to-end acceptance tests verifying core system scenarios.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import httpx
import pytest

from scripts.seed_data import (
    generate_deterministic_demo_payloads,
    generate_historical_transactions,
    generate_synthetic_users,
    run_seed,
)
from services.gateway.main import app
from services.gateway.schemas.transactions import TransactionAcceptedResponse
from services.outbox_publisher.config import OutboxPublisherSettings
from services.outbox_publisher.publisher import OutboxPublisher
from services.processor.config import ProcessorSettings
from services.processor.consumers.compensation_consumer import CompensationConsumer
from services.processor.consumers.transaction_consumer import TransactionConsumer
from services.processor.domain.ml_model import MLAnomalyScorer
from services.processor.domain.rules import evaluate_rules
from services.processor.domain.schemas import RuleDefinition, ScoringWeights, TransactionContext, VelocityContext
from services.processor.scheduler.escalation_scheduler import EscalationScheduler
from services.processor.services.compensation_service import RiskCompensationService
from services.processor.services.detection_pipeline import DetectionPipeline
from services.processor.services.rule_cache import RuleCache
from shared.db.session import get_db_session
from shared.events.envelope import EventEnvelope
from shared.events.event_types import (
    DEFAULT_EVENT_VERSION,
    EVENT_ALERT_CREATED,
    EVENT_RISK_PROFILE_RECALCULATE,
    EVENT_TRANSACTION_CREATED,
    STREAM_TRANSACTIONS,
)
from shared.models import Alert, AuditLog, OutboxEvent, ProcessedEvent, RiskProfile, Transaction
from shared.models.enums import AlertSeverity, AlertStatus, OutboxStatus, RuleType, TransactionStatus


@pytest.fixture
def mock_db_session():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    return mock_session


@pytest.fixture
def test_client(mock_db_session):
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_scenario_clean_startup(test_client, mock_db_session):
    """Clean startup: reports healthy, and empty initial alerts list."""
    mock_count = MagicMock()
    mock_count.scalar_one.return_value = 0
    mock_items = MagicMock()
    mock_items.scalars.return_value.all.return_value = []
    mock_db_session.execute.side_effect = [mock_count, mock_items]

    # Health check
    health_resp = await test_client.get("/healthz")
    assert health_resp.status_code == 200
    assert health_resp.json() == {"status": "ok"}

    # Alerts query returns empty collection
    alerts_resp = await test_client.get("/api/v1/alerts")
    assert alerts_resp.status_code == 200
    data = alerts_resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_scenario_manual_seed():
    """Manual seed tool populates sample users, transactions, and demo scenarios."""
    users = generate_synthetic_users(100)
    txns = generate_historical_transactions(users, count=1000)
    demo_payloads = generate_deterministic_demo_payloads(users)

    assert len(users) >= 100
    assert len(txns) >= 1000
    assert len(demo_payloads) >= 2

    # Dry run seed
    seed_result = await run_seed(user_count=100, txn_count=1000, dry_run=True)
    assert seed_result["status"] == "dry_run"
    assert seed_result["users"] == 100
    assert seed_result["transactions"] == 1000


@pytest.mark.asyncio
async def test_scenario_transaction_processing_and_detection():
    """Transaction submission and processing generates alert when anomaly detected."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    # Rule triggering critical alert
    rule = RuleDefinition(
        id=uuid.uuid4(),
        name="High Value Transaction",
        rule_type=RuleType.AMOUNT_THRESHOLD,
        parameters={"threshold": 5000.0},
        severity=AlertSeverity.CRITICAL,
        enabled=True,
    )
    mock_rule_cache = MagicMock()
    mock_rule_cache.get_active_rules = AsyncMock(return_value=[rule])

    mock_ml = MagicMock()
    mock_ml.score.return_value = Decimal("0.8500")

    pipeline = DetectionPipeline(
        rule_cache=mock_rule_cache,
        ml_detector=mock_ml,
    )

    txn_id = uuid.uuid4()
    user_id = uuid.uuid4()
    envelope = EventEnvelope(
        event_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version=DEFAULT_EVENT_VERSION,
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={
            "transaction_id": str(txn_id),
            "user_id": str(user_id),
            "amount": "9999.00",
            "currency": "USD",
            "country": "US",
            "merchant_category": "luxury_goods",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Empty velocity and profile lookups
    v_mock = MagicMock()
    v_mock.one.return_value = MagicMock(txn_count=0, total_amount=Decimal("0.00"))
    p_mock = MagicMock()
    p_mock.scalar_one_or_none.return_value = None
    mock_session.execute.side_effect = [v_mock, p_mock, MagicMock(), MagicMock()]

    decision = await pipeline.process_transaction_event(
        session=mock_session,
        event_envelope=envelope,
    )

    assert decision.should_alert is True
    assert decision.severity == AlertSeverity.CRITICAL
    mock_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_scenario_analyst_approval_and_audit(test_client, mock_db_session):
    """Analyst approves pending alert, transitions status, and logs audit record."""
    alert_id = uuid.uuid4()
    mock_row = MagicMock(
        id=alert_id,
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="APPROVED",
        severity="HIGH",
    )
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = mock_row
    mock_db_session.execute.return_value = mock_update_res

    response = await test_client.post(
        f"/api/v1/alerts/{alert_id}/approve",
        json={"resolution_reason": "Verified purchase with cardholder"},
        headers={"X-Actor": "analyst_emma"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "APPROVED"
    assert data["resolved_by"] == "analyst_emma"


@pytest.mark.asyncio
async def test_scenario_analyst_block_and_audit(test_client, mock_db_session):
    """Analyst blocks pending alert, transitions status, and logs audit record."""
    alert_id = uuid.uuid4()
    mock_row = MagicMock(
        id=alert_id,
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="BLOCKED",
        severity="CRITICAL",
    )
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = mock_row
    mock_db_session.execute.return_value = mock_update_res

    response = await test_client.post(
        f"/api/v1/alerts/{alert_id}/block",
        json={"resolution_reason": "Card reported lost/stolen"},
        headers={"X-Actor": "analyst_alex"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "BLOCKED"
    assert data["resolved_by"] == "analyst_alex"


@pytest.mark.asyncio
async def test_scenario_false_positive_compensation_flow():
    """False positive alert resolution triggers risk score compensation recalculation."""
    comp_service = RiskCompensationService()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    user_id = uuid.uuid4()
    existing_profile = RiskProfile(
        user_id=user_id,
        risk_score=Decimal("0.8000"),
        total_alerts=5,
        false_positive_count=1,
        last_recalculated_at=datetime.now(timezone.utc),
    )

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = existing_profile
    mock_session.execute.return_value = mock_res

    updated_profile = await comp_service.recalculate_user_risk_profile(
        session=mock_session,
        user_id=user_id,
    )

    assert updated_profile.false_positive_count == 2


@pytest.mark.asyncio
async def test_scenario_escalation_lifecycle():
    """Pending alerts escalate to email and slack tiers on subsequent ticks."""
    scheduler = EscalationScheduler(
        settings=ProcessorSettings(
            ESCALATION_EMAIL_MINUTES=10,
            ESCALATION_SLACK_MINUTES=30,
        )
    )

    now = datetime.now(timezone.utc)
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    # Tier 1 Email query returns an alert
    alert_1 = Alert(
        id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=AlertStatus.PENDING.value,
        severity=AlertSeverity.HIGH.value,
        composite_risk_score=Decimal("0.8500"),
        correlation_id=uuid.uuid4(),
        created_at=now - timedelta(minutes=15),
    )
    mock_email_query = MagicMock()
    mock_email_query.scalars.return_value.all.return_value = [alert_1]

    # Tier 2 Slack query returns empty for this tick
    mock_slack_query = MagicMock()
    mock_slack_query.scalars.return_value.all.return_value = []

    # Update returning row
    mock_upd_res = MagicMock()
    mock_upd_res.fetchone.return_value = MagicMock(
        id=alert_1.id,
        transaction_id=alert_1.transaction_id,
        user_id=alert_1.user_id,
        severity=alert_1.severity,
        composite_risk_score=alert_1.composite_risk_score,
        correlation_id=alert_1.correlation_id,
    )

    mock_session.execute.side_effect = [mock_email_query, mock_upd_res, mock_slack_query]

    email_count, slack_count = await scheduler.run_escalation_tick(session=mock_session, current_time=now)
    assert email_count == 1
    assert slack_count == 0
    mock_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_scenario_escalation_vs_resolution_race():
    """When resolution and escalation occur simultaneously, exactly one conditional update wins."""
    scheduler = EscalationScheduler()
    now = datetime.now(timezone.utc)
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    alert_1 = Alert(
        id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=AlertStatus.PENDING.value,
        severity=AlertSeverity.HIGH.value,
        composite_risk_score=Decimal("0.8500"),
        correlation_id=uuid.uuid4(),
        created_at=now - timedelta(minutes=20),
    )
    mock_email_query = MagicMock()
    mock_email_query.scalars.return_value.all.return_value = [alert_1]

    # Scheduler update finds row already resolved by analyst (fetchone returns None)
    mock_upd = MagicMock()
    mock_upd.fetchone.return_value = None

    mock_slack_query = MagicMock()
    mock_slack_query.scalars.return_value.all.return_value = []

    mock_session.execute.side_effect = [mock_email_query, mock_upd, mock_slack_query]

    email_count, slack_count = await scheduler.run_escalation_tick(session=mock_session, current_time=now)
    assert email_count == 0
    assert slack_count == 0


@pytest.mark.asyncio
async def test_scenario_processor_crash_recovery_zero_duplicate():
    """Unacknowledged messages reclaimed after crash are recognized as already processed."""
    mock_pipeline = MagicMock()
    mock_redis = AsyncMock()
    mock_db = MagicMock()

    consumer = TransactionConsumer(
        pipeline=mock_pipeline,
        settings=ProcessorSettings(
            AUTOCLAIM_MIN_IDLE_TIME_MS=50,
            AUTOCLAIM_INTERVAL_SECONDS=0.05,
        ),
    )

    event_id = uuid.uuid4()
    envelope = EventEnvelope(
        event_id=str(event_id),
        correlation_id=str(uuid.uuid4()),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version=DEFAULT_EVENT_VERSION,
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={"transaction_id": str(uuid.uuid4())},
    )

    mock_redis.xautoclaim.return_value = (
        "0-0",
        [("100-0", {"event": envelope.to_json()})],
        [],
    )

    mock_session = AsyncMock()
    existing_record = ProcessedEvent(
        event_id=event_id,
        consumer_group=consumer.settings.GROUP_TRANSACTIONS,
        processed_at=datetime.now(timezone.utc),
    )
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.return_value = existing_record
    mock_session.execute.return_value = exec_mock
    mock_db.session_factory.return_value.__aenter__.return_value = mock_session

    shutdown_event = asyncio.Event()
    task = asyncio.create_task(
        consumer.run_autoclaim_loop(
            db_manager=mock_db,
            redis_client=mock_redis,
            shutdown_event=shutdown_event,
        )
    )

    await asyncio.sleep(0.12)
    shutdown_event.set()
    await task

    # Pipeline was not re-executed
    mock_pipeline.process_transaction_event.assert_not_called()
    # Message acknowledged
    mock_redis.xack.assert_awaited()


@pytest.mark.asyncio
async def test_scenario_ingestion_resilience_during_redis_outage(test_client):
    """Gateway accepts transaction into PostgreSQL outbox even if Redis is unavailable."""
    original_txn_id = uuid.uuid4()
    idempotency_key = str(uuid.uuid4())

    with patch("services.gateway.services.ingestion.IngestionService.submit_transaction", new_callable=AsyncMock) as mock_submit:
        mock_submit.return_value = TransactionAcceptedResponse(
            transaction_id=original_txn_id,
            status=TransactionStatus.SUBMITTED,
            correlation_id=str(uuid.uuid4()),
            status_url=f"/api/v1/transactions/{original_txn_id}",
        )

        response = await test_client.post(
            "/api/v1/transactions",
            json={
                "idempotency_key": idempotency_key,
                "user_id": str(uuid.uuid4()),
                "amount": "100.00",
                "currency": "USD",
                "country": "US",
                "merchant_category": "retail",
            },
        )
        assert response.status_code == 202
        data = response.json()
        assert data["transaction_id"] == str(original_txn_id)


@pytest.mark.asyncio
async def test_scenario_duplicate_submission_handling(test_client):
    """Submitting with identical idempotency key returns original transaction ID."""
    original_txn_id = uuid.uuid4()
    idempotency_key = str(uuid.uuid4())

    with patch("services.gateway.services.ingestion.IngestionService.submit_transaction", new_callable=AsyncMock) as mock_submit:
        mock_submit.return_value = TransactionAcceptedResponse(
            transaction_id=original_txn_id,
            status=TransactionStatus.SUBMITTED,
            correlation_id=str(uuid.uuid4()),
            status_url=f"/api/v1/transactions/{original_txn_id}",
        )

        response1 = await test_client.post(
            "/api/v1/transactions",
            json={
                "idempotency_key": idempotency_key,
                "user_id": str(uuid.uuid4()),
                "amount": "50.00",
                "currency": "USD",
                "country": "US",
                "merchant_category": "groceries",
            },
        )
        response2 = await test_client.post(
            "/api/v1/transactions",
            json={
                "idempotency_key": idempotency_key,
                "user_id": str(uuid.uuid4()),
                "amount": "50.00",
                "currency": "USD",
                "country": "US",
                "merchant_category": "groceries",
            },
        )

        assert response1.status_code == 202
        assert response2.status_code == 202
        assert response1.json()["transaction_id"] == response2.json()["transaction_id"] == str(original_txn_id)
