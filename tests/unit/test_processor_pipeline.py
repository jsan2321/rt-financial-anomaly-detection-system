"""
Unit tests for Processor DetectionPipeline orchestration service.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from services.processor.domain.demo_strategy import DeterministicDemoStrategy, NullDemoStrategy
from services.processor.domain.schemas import (
    DetectionResult,
    RiskProfileSnapshot,
    RuleDefinition,
    ScoringWeights,
    TransactionContext,
    VelocityContext,
)
from services.processor.services.detection_pipeline import DetectionPipeline
from services.processor.services.rule_cache import RuleCache
from shared.events.envelope import EventEnvelope
from shared.events.event_types import EVENT_ALERT_CREATED, EVENT_TRANSACTION_CREATED
from shared.models import Alert, OutboxEvent, ProcessedEvent, RiskProfile
from shared.models.enums import AlertSeverity, AlertStatus, RuleType, TransactionStatus


class DummyMLScorer:
    """Mock ML scorer returning fixed score."""
    def __init__(self, score_val: Decimal = Decimal("0.1000")) -> None:
        self.score_val = score_val

    def score(self, transaction: TransactionContext, velocity=None) -> Decimal:
        return self.score_val


@pytest.fixture
def mock_rule_cache():
    cache = RuleCache(refresh_ttl_seconds=30.0)
    # Configure with empty rules by default
    cache.set_rules_for_testing([])
    return cache


@pytest.mark.asyncio
async def test_pipeline_normal_transaction_no_alert(mock_rule_cache):
    ml_scorer = DummyMLScorer(score_val=Decimal("0.1000"))
    pipeline = DetectionPipeline(
        rule_cache=mock_rule_cache,
        ml_detector=ml_scorer,
        demo_strategy=NullDemoStrategy(),
        scoring_weights=ScoringWeights(alert_threshold=Decimal("0.60")),
    )

    txn_id = uuid.uuid4()
    user_id = uuid.uuid4()
    event_id = uuid.uuid4()
    corr_id = uuid.uuid4()

    event = EventEnvelope(
        event_id=str(event_id),
        correlation_id=str(corr_id),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={
            "transaction_id": str(txn_id),
            "user_id": str(user_id),
            "amount": "45.00",
            "currency": "USD",
            "country": "US",
            "merchant_category": "groceries",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {},
        },
    )

    mock_session = AsyncMock()

    # Mock velocity query
    mock_vel_row = MagicMock(txn_count=1, total_amount=Decimal("45.00"))
    mock_vel_res = MagicMock()
    mock_vel_res.one.return_value = mock_vel_row

    # Mock risk profile query (None)
    mock_prof_res = MagicMock()
    mock_prof_res.scalar_one_or_none.return_value = None

    # Configure session.execute side effects
    mock_session.execute.side_effect = [
        mock_vel_res,   # velocity lookup
        mock_prof_res,  # risk profile lookup
        MagicMock(),    # update transaction status
    ]

    mock_session.add = MagicMock()

    result = await pipeline.process_transaction_event(mock_session, event)

    assert result.should_alert is False
    assert result.composite_risk_score < Decimal("0.60")

    added_objects = [call[0][0] for call in mock_session.add.call_args_list]

    # Verify ProcessedEvent was added
    processed_events = [obj for obj in added_objects if isinstance(obj, ProcessedEvent)]
    assert len(processed_events) == 1
    assert processed_events[0].event_id == event_id
    assert processed_events[0].consumer_group == "processor-group"

    # Verify NO Alert or OutboxEvent added
    assert len([obj for obj in added_objects if isinstance(obj, Alert)]) == 0
    assert len([obj for obj in added_objects if isinstance(obj, OutboxEvent)]) == 0

    # Verify DB commit was called
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_critical_rule_triggers_alert_and_outbox(mock_rule_cache):
    # Setup rule cache with a critical amount rule
    critical_rule = RuleDefinition(
        id=uuid.uuid4(),
        name="Critical Amount Rule",
        rule_type=RuleType.AMOUNT_THRESHOLD,
        parameters={"threshold": 10000},
        severity=AlertSeverity.CRITICAL,
        enabled=True,
    )
    mock_rule_cache.set_rules_for_testing([critical_rule])

    ml_scorer = DummyMLScorer(score_val=Decimal("0.2000"))
    pipeline = DetectionPipeline(
        rule_cache=mock_rule_cache,
        ml_detector=ml_scorer,
        demo_strategy=NullDemoStrategy(),
        scoring_weights=ScoringWeights(alert_threshold=Decimal("0.60")),
    )

    txn_id = uuid.uuid4()
    user_id = uuid.uuid4()
    event_id = uuid.uuid4()
    corr_id = uuid.uuid4()

    event = EventEnvelope(
        event_id=str(event_id),
        correlation_id=str(corr_id),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={
            "transaction_id": str(txn_id),
            "user_id": str(user_id),
            "amount": "15000.00",
            "currency": "USD",
            "country": "US",
            "merchant_category": "electronics",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {},
        },
    )

    mock_session = AsyncMock()

    # Mock velocity query
    mock_vel_row = MagicMock(txn_count=1, total_amount=Decimal("15000.00"))
    mock_vel_res = MagicMock()
    mock_vel_res.one.return_value = mock_vel_row

    # Mock risk profile query (initial profile exists)
    existing_profile = RiskProfile(
        user_id=user_id,
        risk_score=Decimal("0.1000"),
        total_alerts=0,
        false_positive_count=0,
    )
    mock_prof_res = MagicMock()
    mock_prof_res.scalar_one_or_none.return_value = existing_profile

    # Side effects for executes
    mock_session.execute.side_effect = [
        mock_vel_res,   # velocity lookup
        mock_prof_res,  # risk profile snapshot lookup
        MagicMock(),    # update transaction status
        mock_prof_res,  # risk profile update lookup
    ]

    mock_session.add = MagicMock()

    result = await pipeline.process_transaction_event(mock_session, event)

    assert result.should_alert is True
    assert result.severity == AlertSeverity.CRITICAL

    added_objects = [call[0][0] for call in mock_session.add.call_args_list]

    # Verify Alert row created
    alerts = [obj for obj in added_objects if isinstance(obj, Alert)]
    assert len(alerts) == 1
    assert alerts[0].transaction_id == txn_id
    assert alerts[0].user_id == user_id
    assert alerts[0].status == AlertStatus.PENDING.value
    assert alerts[0].severity == AlertSeverity.CRITICAL.value

    # Verify alert.created OutboxEvent row created
    outbox_events = [obj for obj in added_objects if isinstance(obj, OutboxEvent)]
    assert len(outbox_events) == 1
    assert outbox_events[0].event_type == EVENT_ALERT_CREATED
    assert outbox_events[0].producer_service == "processor"
    assert outbox_events[0].payload["alert_id"] == str(alerts[0].id)
    assert outbox_events[0].payload["transaction_id"] == str(txn_id)

    # Verify RiskProfile alert count was incremented
    assert existing_profile.total_alerts == 1

    # Verify ProcessedEvent recorded
    processed_events = [obj for obj in added_objects if isinstance(obj, ProcessedEvent)]
    assert len(processed_events) == 1
    assert processed_events[0].event_id == event_id

    # Verify DB transaction committed
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_demo_mode_strategy_override(mock_rule_cache):
    ml_scorer = DummyMLScorer(score_val=Decimal("0.0500"))
    pipeline = DetectionPipeline(
        rule_cache=mock_rule_cache,
        ml_detector=ml_scorer,
        demo_strategy=DeterministicDemoStrategy(),  # DEMO_MODE active
        scoring_weights=ScoringWeights(alert_threshold=Decimal("0.60")),
    )

    txn_id = uuid.uuid4()
    user_id = uuid.uuid4()
    event_id = uuid.uuid4()
    corr_id = uuid.uuid4()

    event = EventEnvelope(
        event_id=str(event_id),
        correlation_id=str(corr_id),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={
            "transaction_id": str(txn_id),
            "user_id": str(user_id),
            "amount": "12.50",
            "currency": "USD",
            "country": "US",
            "merchant_category": "coffee",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"demo_scenario": "impossible_travel"},
        },
    )

    mock_session = AsyncMock()
    mock_vel_row = MagicMock(txn_count=1, total_amount=Decimal("12.50"))
    mock_vel_res = MagicMock()
    mock_vel_res.one.return_value = mock_vel_row
    mock_prof_res = MagicMock()
    mock_prof_res.scalar_one_or_none.return_value = None

    mock_session.execute.side_effect = [
        mock_vel_res,
        mock_prof_res,
        MagicMock(),
        mock_prof_res,
    ]

    mock_session.add = MagicMock()

    result = await pipeline.process_transaction_event(mock_session, event)

    assert result.should_alert is True
    assert result.severity == AlertSeverity.CRITICAL
    assert result.is_demo is True

    added_objects = [call[0][0] for call in mock_session.add.call_args_list]

    alerts = [obj for obj in added_objects if isinstance(obj, Alert)]
    assert len(alerts) == 1
    assert alerts[0].is_demo is True
