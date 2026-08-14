"""
OutboxEvent SQLAlchemy model mapping to table 'outbox_events'.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base
from .enums import OutboxStatus


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PUBLISHED', 'DEAD_LETTERED')",
            name="chk_outbox_status",
        ),
        CheckConstraint("retry_count >= 0", name="chk_outbox_retry_count"),
        Index(
            "idx_outbox_pending",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("idx_outbox_correlation_id", "correlation_id"),
    )

    id: uuid.UUID = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    event_type: str = Column(String(128), nullable=False)
    event_version: str = Column(String(16), nullable=False, default="v1", server_default="v1")
    payload: Dict[str, Any] = Column(JSONB, nullable=False)
    correlation_id: uuid.UUID = Column(UUID(as_uuid=True), nullable=False)
    producer_service: str = Column(String(64), nullable=False)
    status: str = Column(
        String(32),
        nullable=False,
        default=OutboxStatus.PENDING.value,
        server_default=OutboxStatus.PENDING.value,
    )
    retry_count: int = Column(Integer, nullable=False, default=0, server_default="0")
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
    )
    published_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<OutboxEvent id={self.id} type={self.event_type} status={self.status}>"
