"""
Transaction request and response schemas for Gateway API.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.models.enums import AlertSeverity, AlertStatus, TransactionStatus


class TransactionCreateRequest(BaseModel):
    """
    Client submission payload for POST /api/v1/transactions.
    Validates strictly with extra fields forbidden.
    """
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(
        gt=Decimal("0.00"),
        description="Transaction amount, must be strictly positive",
    )
    currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        description="ISO 4217 3-letter uppercase currency code",
    )
    country: str = Field(
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 uppercase country code",
    )
    merchant_category: str = Field(
        min_length=1,
        max_length=128,
        description="Merchant Category Code (MCC) or category identifier",
    )
    user_id: uuid.UUID = Field(
        description="UUID of the transacting user",
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Client-supplied deduplication key. Auto-generated as UUIDv4 if omitted.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata (e.g. demo_scenario)",
    )

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        v_upper = v.strip().upper()
        if len(v_upper) != 3 or not v_upper.isalpha():
            raise ValueError("currency must be a valid 3-letter ISO code")
        return v_upper

    @field_validator("country")
    @classmethod
    def validate_country(cls, v: str) -> str:
        v_upper = v.strip().upper()
        if len(v_upper) != 2 or not v_upper.isalpha():
            raise ValueError("country must be a valid 2-letter ISO country code")
        return v_upper


class TransactionAcceptedResponse(BaseModel):
    """Asynchronous acceptance response (HTTP 202 Accepted)."""
    model_config = ConfigDict(frozen=True)

    transaction_id: uuid.UUID
    status: TransactionStatus = TransactionStatus.SUBMITTED
    correlation_id: str
    status_url: str


class AlertSummaryResponse(BaseModel):
    """Brief summary of an associated alert attached to a transaction."""
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    status: str
    severity: str


class TransactionDetailResponse(BaseModel):
    """Full detail response for GET /api/v1/transactions/{id}."""
    model_config = ConfigDict(frozen=True)

    transaction_id: uuid.UUID
    user_id: uuid.UUID
    amount: Decimal
    currency: str
    country: str
    merchant_category: str
    status: TransactionStatus
    created_at: datetime
    processed_at: Optional[datetime] = None
    correlation_id: Optional[uuid.UUID] = None
    alert: Optional[AlertSummaryResponse] = None
