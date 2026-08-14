"""
Composite Risk Scoring & Hybrid Decision Engine for RT-FADS.
Combines rule matches, Isolation Forest ML score, and User Risk Profile.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from shared.models.enums import AlertSeverity

from .schemas import (
    DetectionResult,
    RiskProfileSnapshot,
    RuleMatch,
    ScoringWeights,
    TransactionContext,
)

SEVERITY_VALUES: Dict[str, Decimal] = {
    AlertSeverity.LOW.value: Decimal("0.2500"),
    AlertSeverity.MEDIUM.value: Decimal("0.5000"),
    AlertSeverity.HIGH.value: Decimal("0.7500"),
    AlertSeverity.CRITICAL.value: Decimal("1.0000"),
    AlertSeverity.LOW: Decimal("0.2500"),
    AlertSeverity.MEDIUM: Decimal("0.5000"),
    AlertSeverity.HIGH: Decimal("0.7500"),
    AlertSeverity.CRITICAL: Decimal("1.0000"),
}


def _quantize(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def calculate_rule_severity_score(rule_matches: List[RuleMatch]) -> Decimal:
    """Returns the maximum severity score across all triggered rules, or 0.0000 if none."""
    if not rule_matches:
        return Decimal("0.0000")
    scores = [SEVERITY_VALUES.get(match.severity, Decimal("0.0000")) for match in rule_matches]
    return max(scores)


def compute_composite_risk_score(
    rule_severity_score: Decimal,
    ml_anomaly_score: Decimal,
    user_risk_score: Decimal,
    weights: ScoringWeights,
) -> Decimal:
    """
    Computes weighted composite risk score:
    w_rule * rule_severity + w_ml * ml_anomaly + w_profile * user_risk
    """
    weighted_sum = (
        (weights.w_rule * rule_severity_score)
        + (weights.w_ml * ml_anomaly_score)
        + (weights.w_profile * user_risk_score)
    )
    clamped = max(Decimal("0.0000"), min(Decimal("1.0000"), weighted_sum))
    return _quantize(clamped)


def determine_alert_severity(
    composite_score: Decimal,
    has_critical_rule: bool,
) -> AlertSeverity:
    """Maps composite score and rule overrides to alert severity."""
    if has_critical_rule or composite_score >= Decimal("0.8500"):
        return AlertSeverity.CRITICAL
    elif composite_score >= Decimal("0.7000"):
        return AlertSeverity.HIGH
    elif composite_score >= Decimal("0.5000"):
        return AlertSeverity.MEDIUM
    return AlertSeverity.LOW


def compute_detection_decision(
    transaction: TransactionContext,
    rule_matches: List[RuleMatch],
    ml_score: Decimal,
    risk_profile: Optional[RiskProfileSnapshot] = None,
    weights: Optional[ScoringWeights] = None,
) -> DetectionResult:
    """
    Pure decision function computing composite risk and alert triggers.
    (transaction, rule_matches, ml_score, risk_profile, config) -> DetectionResult
    """
    scoring_weights = weights or ScoringWeights()

    rule_severity_score = calculate_rule_severity_score(rule_matches)
    user_risk_score = (
        _quantize(risk_profile.risk_score)
        if risk_profile
        else Decimal("0.0000")
    )
    ml_anomaly_score = _quantize(ml_score)

    composite_score = compute_composite_risk_score(
        rule_severity_score=rule_severity_score,
        ml_anomaly_score=ml_anomaly_score,
        user_risk_score=user_risk_score,
        weights=scoring_weights,
    )

    has_critical_rule = any(
        match.severity in (AlertSeverity.CRITICAL.value, AlertSeverity.CRITICAL)
        for match in rule_matches
    )

    threshold_triggered = composite_score >= scoring_weights.alert_threshold
    should_alert = threshold_triggered or has_critical_rule

    severity = determine_alert_severity(composite_score, has_critical_rule)

    risk_snapshot_dict = (
        risk_profile.model_dump()
        if risk_profile
        else {
            "user_id": str(transaction.user_id),
            "risk_score": "0.0000",
            "total_alerts": 0,
            "false_positive_count": 0,
        }
    )

    explanation = None
    if should_alert:
        reasons = []
        if has_critical_rule:
            reasons.append("Triggered by CRITICAL severity deterministic fraud rule")
        if threshold_triggered:
            reasons.append(
                f"Composite risk score {composite_score} >= threshold {scoring_weights.alert_threshold}"
            )
        explanation = "; ".join(reasons)

    return DetectionResult(
        should_alert=should_alert,
        severity=severity,
        composite_risk_score=composite_score,
        rule_severity_score=rule_severity_score,
        ml_anomaly_score=ml_anomaly_score,
        user_risk_score=user_risk_score,
        rule_matches=rule_matches,
        risk_profile_snapshot=risk_snapshot_dict,
        is_demo=False,
        explanation=explanation,
    )
