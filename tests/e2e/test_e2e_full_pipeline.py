"""
End-to-end test for full transaction ingestion to alert notification pipeline.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from services.gateway.consumers.notification_forwarder import NotificationForwarder
from services.gateway.schemas.transactions import TransactionCreateRequest
from services.gateway.services.ingestion import IngestionService
from services.outbox_publisher.publisher import OutboxPublisher
from services.processor.consumers.transaction_consumer import TransactionConsumer
from services.processor.domain.schemas import RuleDefinition, ScoringWeights
from services.processor.services.detection_pipeline import DetectionPipeline
from shared.events.envelope import EventEnvelope
from shared.events.event_types import (
    DEFAULT_EVENT_VERSION,
    EVENT_ALERT_CREATED,
    EVENT_TRANSACTION_CREATED,
    PUBSUB_NOTIFICATIONS,
    STREAM_ALERTS,
    STREAM_TRANSACTIONS,
)
from shared.models import Alert, OutboxEvent, Transaction
from shared.models.enums import AlertSeverity, AlertStatus, OutboxStatus, RuleType, TransactionStatus


@pytest.mark.asyncio
async def test_full_pipeline_ingestion_to_notification():
    """
    Traces a transaction across the full pipeline:
    Gateway Ingestion -> Outbox Table -> Outbox Publisher -> Stream:Transactions
    -> Processor Detection -> Alert Outbox -> Outbox Publisher -> Stream:Alerts
    -> Notification Forwarder -> Redis Pub/Sub
    """
    mock_redis = AsyncMock()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    corr_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # 1. Gateway Ingestion creates Transaction & OutboxEvent
    ingestion_service = IngestionService()
    req = TransactionCreateRequest(
        idempotency_key=str(uuid.uuid4()),
        user_id=user_id,
        amount=Decimal("15000.00"),
        currency="USD",
        country="US",
        merchant_category="crypto_exchange",
    )

    # Ingestion DB mock
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = exec_mock

    ingest_resp = await ingestion_service.submit_transaction(
        session=mock_session,
        payload=req,
        correlation_id=str(corr_id),
    )
    assert ingest_resp.status == TransactionStatus.SUBMITTED
    mock_session.commit.assert_awaited()

    # 2. Outbox Publisher relays Transaction Outbox Event
    outbox_publisher = OutboxPublisher()
    txn_outbox_event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version=DEFAULT_EVENT_VERSION,
        payload={
            "transaction_id": str(ingest_resp.transaction_id),
            "user_id": str(user_id),
            "amount": "15000.00",
            "currency": "USD",
            "country": "US",
            "merchant_category": "crypto_exchange",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        correlation_id=corr_id,
        producer_service="gateway",
        status=OutboxStatus.PENDING.value,
        retry_count=0,
        created_at=datetime.now(timezone.utc),
    )

    mock_redis.xadd.return_value = "1001-0"
    msg_id = await outbox_publisher.publish_event(mock_redis, txn_outbox_event)
    assert msg_id == "1001-0"

    # 3. Processor Detection Pipeline processes stream event
    rule = RuleDefinition(
        id=uuid.uuid4(),
        name="High Amount Threshold",
        rule_type=RuleType.AMOUNT_THRESHOLD,
        parameters={"threshold": 10000.0},
        severity=AlertSeverity.CRITICAL,
        enabled=True,
    )
    mock_rule_cache = MagicMock()
    mock_rule_cache.get_active_rules = AsyncMock(return_value=[rule])
    mock_ml = MagicMock()
    mock_ml.score.return_value = Decimal("0.9000")

    pipeline = DetectionPipeline(
        rule_cache=mock_rule_cache,
        ml_detector=mock_ml,
    )

    # Context queries for velocity and risk profile
    v_mock = MagicMock()
    v_mock.one.return_value = MagicMock(txn_count=0, total_amount=Decimal("0.00"))
    p_mock = MagicMock()
    p_mock.scalar_one_or_none.return_value = None
    mock_session.execute.side_effect = [v_mock, p_mock, MagicMock(), MagicMock()]

    event_envelope = EventEnvelope(
        event_id=str(uuid.uuid4()),
        correlation_id=str(corr_id),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version=DEFAULT_EVENT_VERSION,
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload=txn_outbox_event.payload,
    )

    decision = await pipeline.process_transaction_event(
        session=mock_session,
        event_envelope=event_envelope,
    )
    assert decision.should_alert is True
    assert decision.severity == AlertSeverity.CRITICAL

    # 4. Outbox Publisher relays Alert Outbox Event to stream:alerts
    alert_outbox_event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_ALERT_CREATED,
        event_version=DEFAULT_EVENT_VERSION,
        payload={
            "alert_id": str(uuid.uuid4()),
            "transaction_id": str(ingest_resp.transaction_id),
            "user_id": str(user_id),
            "status": AlertStatus.PENDING.value,
            "severity": decision.severity.value,
            "composite_risk_score": str(decision.composite_risk_score),
            "ml_anomaly_score": str(decision.ml_anomaly_score),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        correlation_id=corr_id,
        producer_service="processor",
        status=OutboxStatus.PENDING.value,
        retry_count=0,
        created_at=datetime.now(timezone.utc),
    )

    alert_msg_id = await outbox_publisher.publish_event(mock_redis, alert_outbox_event)
    assert alert_msg_id == "1001-0"

    # 5. Gateway Notification Forwarder broadcasts to Redis Pub/Sub
    forwarder = NotificationForwarder()
    alert_envelope = EventEnvelope(
        event_id=str(alert_outbox_event.id),
        correlation_id=str(corr_id),
        event_type=EVENT_ALERT_CREATED,
        event_version=DEFAULT_EVENT_VERSION,
        occurred_at=datetime.now(timezone.utc),
        producer_service="processor",
        payload=alert_outbox_event.payload,
    )

    await forwarder.process_stream_message(
        redis_client=mock_redis,
        stream_name=STREAM_ALERTS,
        message_id="2001-0",
        message_data={"event": alert_envelope.to_json()},
    )

    # Verify message was published to Redis Pub/Sub topic
    mock_redis.publish.assert_awaited_once()
    pubsub_channel_arg = mock_redis.publish.call_args[0][0]
    assert pubsub_channel_arg == PUBSUB_NOTIFICATIONS
