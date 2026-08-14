"""
Unit tests for shared.models (ORM models and enums).
"""

from decimal import Decimal
import uuid
from datetime import datetime, timezone

from shared.models.enums import (
    TransactionStatus,
    AlertStatus,
    AlertSeverity,
    RuleType,
    OutboxStatus,
)
from shared.models.transaction import Transaction
from shared.models.alert import Alert
from shared.models.risk_profile import RiskProfile
from shared.models.outbox import OutboxEvent
from shared.models.processed_event import ProcessedEvent
from shared.models.dead_letter import DeadLetterEvent


def test_enum_properties():
    # AlertStatus terminal checks
    assert AlertStatus.APPROVED.is_terminal is True
    assert AlertStatus.BLOCKED.is_terminal is True
    assert AlertStatus.FALSE_POSITIVE.is_terminal is True
    assert AlertStatus.PENDING.is_terminal is False
    assert AlertStatus.ESCALATED_EMAIL.is_terminal is False

    # AlertStatus escalation checks
    assert AlertStatus.ESCALATED_EMAIL.is_escalated is True
    assert AlertStatus.ESCALATED_SLACK.is_escalated is True
    assert AlertStatus.PENDING.is_escalated is False

    # RuleType constants
    assert RuleType.AMOUNT_THRESHOLD == "AMOUNT_THRESHOLD"
    assert RuleType.HIGH_RISK_COUNTRY == "HIGH_RISK_COUNTRY"
    assert RuleType.VELOCITY == "VELOCITY"
    assert RuleType.USER_RISK_LEVEL == "USER_RISK_LEVEL"
    assert RuleType.MERCHANT_CATEGORY == "MERCHANT_CATEGORY"

    # OutboxStatus
    assert OutboxStatus.PENDING == "PENDING"
    assert OutboxStatus.PUBLISHED == "PUBLISHED"
    assert OutboxStatus.DEAD_LETTERED == "DEAD_LETTERED"


def test_transaction_model_instantiation():
    tx_id = uuid.uuid4()
    user_id = uuid.uuid4()
    cid = uuid.uuid4()
    tx = Transaction(
        id=tx_id,
        user_id=user_id,
        amount=Decimal("250.00"),
        currency="USD",
        country="US",
        merchant_category="electronics",
        idempotency_key="idemp-123",
        correlation_id=cid,
    )
    assert tx.id == tx_id
    assert tx.amount == Decimal("250.00")
    assert tx.currency == "USD"
    assert "Transaction" in repr(tx)


def test_alert_model_instantiation():
    alt_id = uuid.uuid4()
    tx_id = uuid.uuid4()
    user_id = uuid.uuid4()
    cid = uuid.uuid4()
    alt = Alert(
        id=alt_id,
        transaction_id=tx_id,
        user_id=user_id,
        status=AlertStatus.PENDING.value,
        severity=AlertSeverity.HIGH.value,
        composite_risk_score=Decimal("0.8500"),
        ml_anomaly_score=Decimal("0.7200"),
        correlation_id=cid,
    )
    assert alt.id == alt_id
    assert alt.composite_risk_score == Decimal("0.8500")
    assert alt.status == AlertStatus.PENDING.value
    assert "Alert" in repr(alt)


def test_risk_profile_model_instantiation():
    user_id = uuid.uuid4()
    rp = RiskProfile(
        user_id=user_id,
        risk_score=Decimal("0.3500"),
        total_alerts=5,
        false_positive_count=1,
    )
    assert rp.user_id == user_id
    assert rp.risk_score == Decimal("0.3500")
    assert rp.total_alerts == 5
    assert "RiskProfile" in repr(rp)


def test_outbox_event_model_instantiation():
    eid = uuid.uuid4()
    cid = uuid.uuid4()
    outbox = OutboxEvent(
        id=eid,
        event_type="transaction.created",
        payload={"amount": 50},
        correlation_id=cid,
        producer_service="gateway",
        status=OutboxStatus.PENDING.value,
        retry_count=0,
    )
    assert outbox.id == eid
    assert outbox.status == OutboxStatus.PENDING.value
    assert outbox.retry_count == 0
    assert "OutboxEvent" in repr(outbox)


def test_processed_and_dead_letter_models():
    eid = uuid.uuid4()
    pe = ProcessedEvent(event_id=eid, consumer_group="processor-group")
    assert pe.event_id == eid
    assert pe.consumer_group == "processor-group"
    assert "ProcessedEvent" in repr(pe)

    dl = DeadLetterEvent(
        original_event_id=eid,
        event_type="transaction.created",
        payload={"amount": 100},
        error_message="Connection timeout",
        retry_count=5,
        stream_name="stream:transactions",
    )
    assert dl.original_event_id == eid
    assert dl.retry_count == 5
    assert "DeadLetterEvent" in repr(dl)
