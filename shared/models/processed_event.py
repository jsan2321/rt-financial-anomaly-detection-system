"""
ProcessedEvent SQLAlchemy model mapping to table 'processed_events'.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id: uuid.UUID = Column(UUID(as_uuid=True), primary_key=True)
    consumer_group: str = Column(String(64), primary_key=True)
    processed_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
    )

    def __repr__(self) -> str:
        return f"<ProcessedEvent event_id={self.event_id} group={self.consumer_group}>"
