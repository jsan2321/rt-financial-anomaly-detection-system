"""
RiskProfile SQLAlchemy model mapping to table 'risk_profiles'.
"""

from datetime import datetime, timezone
from decimal import Decimal
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    Numeric,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from .base import Base


class RiskProfile(Base):
    __tablename__ = "risk_profiles"
    __table_args__ = (
        CheckConstraint("risk_score >= 0.0 AND risk_score <= 1.0", name="chk_risk_profiles_score_range"),
        CheckConstraint("total_alerts >= 0", name="chk_risk_profiles_total_alerts_positive"),
        CheckConstraint("false_positive_count >= 0", name="chk_risk_profiles_fp_positive"),
    )

    user_id: uuid.UUID = Column(UUID(as_uuid=True), primary_key=True)
    risk_score: Decimal = Column(
        Numeric(precision=5, scale=4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default="0.0000",
    )
    total_alerts: int = Column(Integer, nullable=False, default=0, server_default="0")
    false_positive_count: int = Column(Integer, nullable=False, default=0, server_default="0")
    last_recalculated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
    )

    def __repr__(self) -> str:
        return f"<RiskProfile user={self.user_id} score={self.risk_score} alerts={self.total_alerts}>"
