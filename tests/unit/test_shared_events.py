"""
Unit tests for shared.events (EventEnvelope & event types).
"""

from datetime import datetime, timezone
import json
import uuid
import pytest
from pydantic import ValidationError

from shared.events.envelope import EventEnvelope
from shared.events.event_types import (
    STREAM_TRANSACTIONS,
    STREAM_ALERTS,
    STREAM_ESCALATIONS,
    STREAM_COMPENSATION,
    STREAM_DLQ_PREFIX,
    EVENT_TRANSACTION_CREATED,
    EVENT_ALERT_CREATED,
    EVENT_ALERT_APPROVED,
    EVENT_ALERT_BLOCKED,
    EVENT_ALERT_FALSE_POSITIVE,
    EVENT_ESCALATION_EMAIL_REQUESTED,
    EVENT_ESCALATION_SLACK_REQUESTED,
    EVENT_RISK_PROFILE_RECALCULATE,
    DEFAULT_EVENT_VERSION,
)
from shared.context.correlation import correlation_scope


def test_event_constants():
    assert STREAM_TRANSACTIONS == "stream:transactions"
    assert STREAM_ALERTS == "stream:alerts"
    assert STREAM_ESCALATIONS == "stream:escalations"
    assert STREAM_COMPENSATION == "stream:compensation"
    assert STREAM_DLQ_PREFIX == "stream:dlq"
    assert EVENT_TRANSACTION_CREATED == "transaction.created"
    assert EVENT_ALERT_CREATED == "alert.created"
    assert EVENT_ALERT_APPROVED == "alert.approved"
    assert EVENT_ALERT_BLOCKED == "alert.blocked"
    assert EVENT_ALERT_FALSE_POSITIVE == "alert.false_positive"
    assert EVENT_ESCALATION_EMAIL_REQUESTED == "escalation.email.requested"
    assert EVENT_ESCALATION_SLACK_REQUESTED == "escalation.slack.requested"
    assert EVENT_RISK_PROFILE_RECALCULATE == "risk_profile.recalculate"
    assert DEFAULT_EVENT_VERSION == "1.0"


def test_event_envelope_creation():
    with correlation_scope("test-trace-123"):
        envelope = EventEnvelope(
            event_type=EVENT_TRANSACTION_CREATED,
            producer_service="gateway",
            payload={"transaction_id": "tx-1", "amount": 100.50},
        )

        assert envelope.event_type == EVENT_TRANSACTION_CREATED
        assert envelope.producer_service == "gateway"
        assert envelope.payload == {"transaction_id": "tx-1", "amount": 100.50}
        assert envelope.correlation_id == "test-trace-123"
        assert envelope.event_version == "1.0"
        assert isinstance(envelope.occurred_at, datetime)
        # Check event_id is valid UUID
        assert uuid.UUID(envelope.event_id)


def test_event_envelope_serialization_roundtrip():
    envelope = EventEnvelope(
        event_id="d3b07384-d113-4674-8d48-8c105e463567",
        correlation_id="c9a646d3-9c61-4cd7-bf15-4702941556cb",
        event_type=EVENT_ALERT_CREATED,
        event_version="1.0",
        occurred_at=datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc),
        producer_service="processor",
        payload={"alert_id": "alt-99", "severity": "HIGH"},
    )

    json_str = envelope.to_json()
    assert isinstance(json_str, str)

    restored = EventEnvelope.from_json(json_str)
    assert restored.event_id == envelope.event_id
    assert restored.correlation_id == envelope.correlation_id
    assert restored.event_type == envelope.event_type
    assert restored.event_version == envelope.event_version
    assert restored.occurred_at == envelope.occurred_at
    assert restored.producer_service == envelope.producer_service
    assert restored.payload == envelope.payload

    # Test dict conversion
    as_dict = envelope.to_dict()
    assert isinstance(as_dict, dict)
    from_d = EventEnvelope.from_dict(as_dict)
    assert from_d.event_id == envelope.event_id


def test_event_envelope_forbid_extra_fields():
    data = {
        "event_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "event_type": EVENT_TRANSACTION_CREATED,
        "event_version": "1.0",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "producer_service": "gateway",
        "payload": {},
        "unexpected_extra_field": "disallowed",
    }
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(data)


def test_event_envelope_missing_required_fields():
    with pytest.raises(ValidationError):
        EventEnvelope(event_type=EVENT_TRANSACTION_CREATED)  # Missing producer_service and payload
