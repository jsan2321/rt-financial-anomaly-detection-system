"""
Pydantic schemas for Gateway Alert lifecycle and analyst action endpoints.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from shared.models.enums import AlertSeverity, AlertStatus


class AlertResolutionRequest(BaseModel):
    """Payload for resolving an alert (approve, block, false-positive)."""
    model_config = ConfigDict(extra="forbid")

    resolution_reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional analyst notes explaining the resolution decision",
    )


class AlertSummaryItem(BaseModel):
    """Compact summary item returned in alert list queries."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_id: uuid.UUID
    user_id: uuid.UUID
    status: AlertStatus
    severity: AlertSeverity
    composite_risk_score: Decimal = Field(description="Normalized composite risk score [0.0, 1.0]")
    is_demo: bool = Field(description="Flag indicating if alert was generated under DEMO_MODE")
    created_at: datetime


class AlertListResponse(BaseModel):
    """Paginated list response for alerts query."""
    items: List[AlertSummaryItem]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=500)
    total: int = Field(ge=0)


class AlertDetailResponse(BaseModel):
    """Full detail view of an alert including explanation context and history."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_id: uuid.UUID
    user_id: uuid.UUID
    status: AlertStatus
    severity: AlertSeverity
    composite_risk_score: Decimal
    ml_anomaly_score: Decimal
    rule_matches: List[Dict[str, Any]]
    risk_profile_snapshot: Dict[str, Any]
    is_demo: bool
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_reason: Optional[str] = None
    escalated_email_at: Optional[datetime] = None
    escalated_slack_at: Optional[datetime] = None
    correlation_id: uuid.UUID
    created_at: datetime


class AlertResolutionResponse(BaseModel):
    """Response returned upon successful alert resolution."""
    alert_id: uuid.UUID
    status: AlertStatus
    resolved_by: str
    resolved_at: datetime
    resolution_reason: Optional[str] = None
    correlation_id: str
