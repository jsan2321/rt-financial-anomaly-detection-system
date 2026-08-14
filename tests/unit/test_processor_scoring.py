"""
Unit tests for Composite Risk Scoring and Hybrid Decision Engine.
Tests weighted scoring formulas, critical rule overrides, thresholds, and explainability.
"""

from datetime import datetime, timezone
from decimal import Decimal
import uuid
import pytest

from shared.models.enums import AlertSeverity
from services.processor.domain.composite_scoring import (
    calculate_rule_severity_score,
    compute_composite_risk_score,
    compute_detection_decision,
    determine_alert_severity,
)
from services.processor.domain.schemas import (
    RiskProfileSnapshot,
    RuleMatch,
    ScoringWeights,
    TransactionContext,
)


@pytest.fixture
def sample_transaction() -> TransactionContext:
    return TransactionContext(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        amount=Decimal("2000.00"),
        currency="USD",
        country="US",
        merchant_category="retail",
    )


class TestCompositeScoringMath:
    def test_empty_rules_yields_zero_severity(self):
        assert calculate_rule_severity_score([]) == Decimal("0.0000")

    def test_maximum_severity_selection(self):
        matches = [
            RuleMatch(
                rule_id=str(uuid.uuid4()),
                rule_name="Low Rule",
                rule_type="AMOUNT_THRESHOLD",
                severity="LOW",
                explanation="Low match",
            ),
            RuleMatch(
                rule_id=str(uuid.uuid4()),
                rule_name="High Rule",
                rule_type="VELOCITY",
                severity="HIGH",
                explanation="High match",
            ),
        ]
        # LOW is 0.25, HIGH is 0.75 -> max is 0.75
        assert calculate_rule_severity_score(matches) == Decimal("0.7500")

    def test_weighted_formula_default_weights(self):
        # Default: 0.5 * rule + 0.3 * ml + 0.2 * profile
        weights = ScoringWeights()
        score = compute_composite_risk_score(
            rule_severity_score=Decimal("0.7500"),  # HIGH
            ml_anomaly_score=Decimal("0.6000"),
            user_risk_score=Decimal("0.5000"),
            weights=weights,
        )
        # 0.5*0.75 + 0.3*0.60 + 0.2*0.50 = 0.375 + 0.18 + 0.10 = 0.6550
        assert score == Decimal("0.6550")

    def test_score_clamped_to_one(self):
        weights = ScoringWeights()
        score = compute_composite_risk_score(
            rule_severity_score=Decimal("1.0000"),
            ml_anomaly_score=Decimal("1.0000"),
            user_risk_score=Decimal("1.0000"),
            weights=weights,
        )
        assert score == Decimal("1.0000")


class TestHybridDecisionLogic:
    def test_benign_transaction_does_not_alert(self, sample_transaction):
        decision = compute_detection_decision(
            transaction=sample_transaction,
            rule_matches=[],
            ml_score=Decimal("0.1000"),
            risk_profile=None,
        )
        # Composite: 0.5*0 + 0.3*0.1 + 0.2*0 = 0.0300 < 0.60
        assert decision.should_alert is False
        assert decision.composite_risk_score == Decimal("0.0300")
        assert decision.is_demo is False

    def test_critical_rule_overrides_score_and_forces_alert(self, sample_transaction):
        critical_match = RuleMatch(
            rule_id=str(uuid.uuid4()),
            rule_name="Sanctioned Country",
            rule_type="HIGH_RISK_COUNTRY",
            severity=AlertSeverity.CRITICAL.value,
            explanation="Critical sanctioned country",
        )
        decision = compute_detection_decision(
            transaction=sample_transaction,
            rule_matches=[critical_match],
            ml_score=Decimal("0.0000"),  # Even with 0 ML score
            risk_profile=None,
        )
        assert decision.should_alert is True
        assert decision.severity == AlertSeverity.CRITICAL
        assert "CRITICAL severity" in decision.explanation

    def test_threshold_boundary_decision(self, sample_transaction):
        weights = ScoringWeights(alert_threshold=Decimal("0.60"))

        # Score just below threshold (0.5900)
        # 0.5 * 0.50 (MEDIUM=0.50) + 0.3 * 0.80 + 0.2 * 0.50 = 0.25 + 0.24 + 0.10 = 0.5900
        med_match = RuleMatch(
            rule_id=str(uuid.uuid4()),
            rule_name="Med Rule",
            rule_type="AMOUNT_THRESHOLD",
            severity="MEDIUM",
            explanation="Med match",
        )
        risk_profile = RiskProfileSnapshot(
            user_id=sample_transaction.user_id,
            risk_score=Decimal("0.5000"),
        )
        decision_sub = compute_detection_decision(
            transaction=sample_transaction,
            rule_matches=[med_match],
            ml_score=Decimal("0.8000"),
            risk_profile=risk_profile,
            weights=weights,
        )
        assert decision_sub.composite_risk_score == Decimal("0.5900")
        assert decision_sub.should_alert is False

        # Score meeting threshold (0.6000)
        # ml_score = 0.8333 -> 0.25 + 0.25 + 0.10 = 0.6000
        decision_at = compute_detection_decision(
            transaction=sample_transaction,
            rule_matches=[med_match],
            ml_score=Decimal("0.8334"),
            risk_profile=risk_profile,
            weights=weights,
        )
        assert decision_at.composite_risk_score >= Decimal("0.6000")
        assert decision_at.should_alert is True

    def test_explainability_payload_integrity(self, sample_transaction):
        rule_match = RuleMatch(
            rule_id=str(uuid.uuid4()),
            rule_name="High Rule",
            rule_type="AMOUNT_THRESHOLD",
            severity="HIGH",
            explanation="Amount exceeded",
        )
        risk_profile = RiskProfileSnapshot(
            user_id=sample_transaction.user_id,
            risk_score=Decimal("0.4000"),
            total_alerts=1,
            false_positive_count=0,
        )
        decision = compute_detection_decision(
            transaction=sample_transaction,
            rule_matches=[rule_match],
            ml_score=Decimal("0.7000"),
            risk_profile=risk_profile,
        )
        assert len(decision.rule_matches) == 1
        assert decision.rule_matches[0].rule_name == "High Rule"
        assert decision.risk_profile_snapshot["risk_score"] == Decimal("0.4000")
        assert decision.risk_profile_snapshot["total_alerts"] == 1
