"""
Transaction SQLAlchemy model mapping to TimescaleDB hypertable 'transactions'.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base
from .enums import TransactionStatus


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        PrimaryKeyConstraint("id", "created_at", name="pk_transactions"),
        CheckConstraint("amount > 0", name="chk_transactions_amount_positive"),
        CheckConstraint(
            "status IN ('SUBMITTED', 'PROCESSING', 'PROCESSED', 'PROCESSING_FAILED')",
            name="chk_transactions_status",
        ),
        Index("idx_transactions_idempotency_key", "idempotency_key", "created_at", unique=True),
        Index("idx_transactions_user_created_at", "user_id", text("created_at DESC")),
        Index("idx_transactions_correlation_id", "correlation_id"),
    )

    id: uuid.UUID = Column(
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
    )
    user_id: uuid.UUID = Column(UUID(as_uuid=True), nullable=False)
    amount: Decimal = Column(Numeric(precision=14, scale=2), nullable=False)
    currency: str = Column(String(3), nullable=False, default="USD", server_default="USD")
    country: str = Column(String(2), nullable=False)
    merchant_category: str = Column(String(100), nullable=False)
    status: str = Column(
        String(32),
        nullable=False,
        default=TransactionStatus.SUBMITTED.value,
        server_default=TransactionStatus.SUBMITTED.value,
    )
    idempotency_key: str = Column(String(255), nullable=False)
    metadata_: Optional[Dict[str, Any]] = Column("metadata", JSONB, nullable=True, default=dict, server_default="{}")
    correlation_id: uuid.UUID = Column(UUID(as_uuid=True), nullable=False)
    processed_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} user={self.user_id} amount={self.amount} status={self.status}>"
