"""
DeadLetterEvent SQLAlchemy model mapping to table 'dead_letter_events'.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base


class DeadLetterEvent(Base):
    __tablename__ = "dead_letter_events"

    id: uuid.UUID = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    original_event_id: uuid.UUID = Column(UUID(as_uuid=True), nullable=False)
    event_type: str = Column(String(128), nullable=False)
    payload: Dict[str, Any] = Column(JSONB, nullable=False)
    error_message: str = Column(Text, nullable=False)
    retry_count: int = Column(Integer, nullable=False)
    stream_name: str = Column(String(128), nullable=False)
    consumer_group: Optional[str] = Column(String(64), nullable=True)
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
    )

    def __repr__(self) -> str:
        return f"<DeadLetterEvent id={self.id} orig={self.original_event_id} stream={self.stream_name}>"
