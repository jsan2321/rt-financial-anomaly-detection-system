"""
Standard Event Envelope for all Redis Streams messages in RT-FADS.
Conforms to SRS §7.1 and docs/api/event-contracts.md.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Generic, Optional, TypeVar
import json
import uuid

from pydantic import BaseModel, ConfigDict, Field

from shared.context.correlation import get_correlation_id

T = TypeVar("T")


class EventEnvelope(BaseModel, Generic[T]):
    """
    Uniform versioned event envelope providing distributed tracing and idempotency.
    All cross-service messages MUST be wrapped in this envelope.
    """
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )

    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for idempotency tracking in ProcessedEvent ledger"
    )
    correlation_id: str = Field(
        default_factory=get_correlation_id,
        description="Trace correlation ID linking logs, spans, and database rows"
    )
    event_type: str = Field(
        ...,
        description="Dot-notated event name, e.g. transaction.created, alert.created"
    )
    event_version: str = Field(
        default="1.0",
        description="Semantic schema version for forward/backward compatibility"
    )
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC ISO-8601 timestamp when the event occurred"
    )
    producer_service: str = Field(
        ...,
        description="Service generating the event (e.g. gateway, processor, outbox_publisher)"
    )
    payload: T = Field(
        ...,
        description="Domain payload data"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert envelope to dictionary representation."""
        return self.model_dump(mode="json")

    def to_json(self) -> str:
        """Serialize envelope to JSON string."""
        return self.model_dump_json()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventEnvelope[Any]":
        """Deserialize envelope from dictionary."""
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> "EventEnvelope[Any]":
        """Deserialize envelope from JSON string."""
        data = json.loads(json_str)
        return cls.model_validate(data)
