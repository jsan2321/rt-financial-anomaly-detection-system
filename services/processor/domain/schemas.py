"""
Domain schemas and transfer objects for RT-FADS detection pipeline.
Pure Pydantic models for transactions, rules, matches, contexts, and detection results.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from shared.models.enums import AlertSeverity, RuleType


class TransactionContext(BaseModel):
    """Normalized transaction data presented for fraud evaluation."""
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    user_id: uuid.UUID
    amount: Decimal = Field(gt=Decimal("0.00"), description="Transaction amount in currency unit")
    currency: str = Field(default="USD", min_length=3, max_length=3)
    country: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2 country code")
    merchant_category: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[uuid.UUID] = None


class VelocityContext(BaseModel):
    """Aggregated rolling window statistics for transaction velocity."""
    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    window_minutes: int = Field(default=10, ge=1)
    transaction_count: int = Field(default=0, ge=0)
    total_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))


class RiskProfileSnapshot(BaseModel):
    """Snapshot of user risk profile metrics at decision time."""
    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    risk_score: Decimal = Field(
        default=Decimal("0.0000"),
        ge=Decimal("0.0000"),
        le=Decimal("1.0000"),
    )
    total_alerts: int = Field(default=0, ge=0)
    false_positive_count: int = Field(default=0, ge=0)
    last_recalculated_at: Optional[datetime] = None


class RuleDefinition(BaseModel):
    """Deterministic fraud rule configuration loaded from persistent store."""
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    name: str
    rule_type: RuleType
    parameters: Dict[str, Any] = Field(default_factory=dict)
    severity: AlertSeverity
    enabled: bool = True


class RuleMatch(BaseModel):
    """Structured result when a deterministic fraud rule triggers."""
    model_config = ConfigDict(frozen=True)

    rule_id: str
    rule_name: str
    rule_type: str
    severity: str
    explanation: str
    parameters_snapshot: Dict[str, Any] = Field(default_factory=dict)
    matched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScoringWeights(BaseModel):
    """Configurable weights and thresholds for composite risk scoring."""
    model_config = ConfigDict(frozen=True)

    w_rule: Decimal = Field(default=Decimal("0.5"), ge=Decimal("0.0"), le=Decimal("1.0"))
    w_ml: Decimal = Field(default=Decimal("0.3"), ge=Decimal("0.0"), le=Decimal("1.0"))
    w_profile: Decimal = Field(default=Decimal("0.2"), ge=Decimal("0.0"), le=Decimal("1.0"))
    alert_threshold: Decimal = Field(default=Decimal("0.60"), ge=Decimal("0.0"), le=Decimal("1.0"))


class DetectionResult(BaseModel):
    """Complete, explainable outcome of the hybrid detection pipeline."""
    model_config = ConfigDict(frozen=True)

    should_alert: bool
    severity: AlertSeverity
    composite_risk_score: Decimal = Field(ge=Decimal("0.0000"), le=Decimal("1.0000"))
    rule_severity_score: Decimal = Field(ge=Decimal("0.0000"), le=Decimal("1.0000"))
    ml_anomaly_score: Decimal = Field(ge=Decimal("0.0000"), le=Decimal("1.0000"))
    user_risk_score: Decimal = Field(ge=Decimal("0.0000"), le=Decimal("1.0000"))
    rule_matches: List[RuleMatch] = Field(default_factory=list)
    risk_profile_snapshot: Dict[str, Any] = Field(default_factory=dict)
    is_demo: bool = False
    explanation: Optional[str] = None
