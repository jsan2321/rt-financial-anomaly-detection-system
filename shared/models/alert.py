"""
Alert SQLAlchemy model mapping to table 'alerts'.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base
from .enums import AlertSeverity, AlertStatus


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'ESCALATED_EMAIL', 'ESCALATED_SLACK', 'APPROVED', 'BLOCKED', 'FALSE_POSITIVE')",
            name="chk_alerts_status",
        ),
        CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="chk_alerts_severity",
        ),
        CheckConstraint(
            "composite_risk_score >= 0.0 AND composite_risk_score <= 1.0",
            name="chk_alerts_composite_score",
        ),
        CheckConstraint(
            "ml_anomaly_score >= 0.0 AND ml_anomaly_score <= 1.0",
            name="chk_alerts_ml_score",
        ),
        Index("idx_alerts_status", "status"),
        Index("idx_alerts_status_created_at", "status", "created_at"),
        Index("idx_alerts_user_id", "user_id"),
        Index("idx_alerts_correlation_id", "correlation_id"),
    )

    id: uuid.UUID = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    transaction_id: uuid.UUID = Column(UUID(as_uuid=True), unique=True, nullable=False)
    user_id: uuid.UUID = Column(UUID(as_uuid=True), nullable=False)
    status: str = Column(
        String(32),
        nullable=False,
        default=AlertStatus.PENDING.value,
        server_default=AlertStatus.PENDING.value,
    )
    severity: str = Column(String(32), nullable=False, default=AlertSeverity.HIGH.value)
    composite_risk_score: Decimal = Column(Numeric(precision=5, scale=4), nullable=False)
    ml_anomaly_score: Decimal = Column(Numeric(precision=5, scale=4), nullable=False)
    rule_matches: List[Dict[str, Any]] = Column(JSONB, nullable=False, default=list, server_default="[]")
    risk_profile_snapshot: Dict[str, Any] = Column(JSONB, nullable=False, default=dict, server_default="{}")
    is_demo: bool = Column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    resolved_by: Optional[str] = Column(String(255), nullable=True)
    resolved_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    resolution_reason: Optional[str] = Column(Text, nullable=True)
    escalated_email_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    escalated_slack_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    correlation_id: uuid.UUID = Column(UUID(as_uuid=True), nullable=False)
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
    )

    def __repr__(self) -> str:
        return f"<Alert id={self.id} txn={self.transaction_id} status={self.status} severity={self.severity}>"
