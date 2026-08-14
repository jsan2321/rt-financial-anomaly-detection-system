"""
AuditLog SQLAlchemy model mapping to table 'audit_logs'.
Append-only ledger of state transitions and administrative mutations.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import Column, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_entity", "entity_type", "entity_id"),
        Index("idx_audit_logs_created_at", "created_at"),
        Index("idx_audit_logs_correlation_id", "correlation_id"),
    )

    id: uuid.UUID = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    actor: str = Column(String(255), nullable=False)
    action: str = Column(String(64), nullable=False)
    entity_type: str = Column(String(64), nullable=False)
    entity_id: str = Column(String(255), nullable=False)
    before: Optional[Dict[str, Any]] = Column(JSONB, nullable=True)
    after: Optional[Dict[str, Any]] = Column(JSONB, nullable=True)
    correlation_id: Optional[uuid.UUID] = Column(UUID(as_uuid=True), nullable=True)
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} actor='{self.actor}' action='{self.action}' entity={self.entity_type}:{self.entity_id}>"
