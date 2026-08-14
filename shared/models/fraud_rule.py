"""
FraudRule SQLAlchemy model mapping to table 'fraud_rules'.
Django-owned table read by Processor service.
"""

from datetime import datetime, timezone
from typing import Any, Dict
import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base
from .enums import AlertSeverity, RuleType


class FraudRule(Base):
    __tablename__ = "fraud_rules"
    __table_args__ = (
        Index("idx_fraud_rules_enabled", "enabled"),
    )

    id: uuid.UUID = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: str = Column(String(255), nullable=False)
    rule_type: str = Column(String(64), nullable=False)
    parameters: Dict[str, Any] = Column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    severity: str = Column(
        String(32), nullable=False, default=AlertSeverity.HIGH.value
    )
    enabled: bool = Column(
        Boolean, nullable=False, default=True, server_default=text("TRUE")
    )
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<FraudRule id={self.id} name='{self.name}' type={self.rule_type} enabled={self.enabled}>"
