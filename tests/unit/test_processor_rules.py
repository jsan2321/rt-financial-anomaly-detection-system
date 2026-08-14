"""
Unit tests for deterministic fraud rules evaluation engine.
Tests all five rule types, boundary conditions, disabled rules, and multi-rule collections.
"""

from datetime import datetime, timezone
from decimal import Decimal
import uuid
import pytest

from shared.models.enums import AlertSeverity, RuleType
from services.processor.domain.rules import evaluate_rule, evaluate_rules
from services.processor.domain.schemas import (
    RiskProfileSnapshot,
    RuleDefinition,
    TransactionContext,
    VelocityContext,
)


@pytest.fixture
def base_transaction() -> TransactionContext:
    return TransactionContext(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        amount=Decimal("1500.00"),
        currency="USD",
        country="US",
        merchant_category="electronics",
        created_at=datetime.now(timezone.utc),
    )


class TestAmountThresholdRule:
    def test_amount_exceeds_threshold_triggers_match(self, base_transaction):
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="Large Amount Rule",
            rule_type=RuleType.AMOUNT_THRESHOLD,
            parameters={"threshold": 1000.00},
            severity=AlertSeverity.HIGH,
        )
        match = evaluate_rule(rule, base_transaction)
        assert match is not None
        assert match.rule_name == "Large Amount Rule"
        assert match.severity == AlertSeverity.HIGH.value
        assert "exceeds threshold 1000" in match.explanation

    def test_amount_below_threshold_does_not_trigger(self, base_transaction):
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="Large Amount Rule",
            rule_type=RuleType.AMOUNT_THRESHOLD,
            parameters={"threshold": 5000.00},
            severity=AlertSeverity.HIGH,
        )
        match = evaluate_rule(rule, base_transaction)
        assert match is None

    def test_currency_matching(self, base_transaction):
        rule_eur = RuleDefinition(
            id=uuid.uuid4(),
            name="EUR Large Amount",
            rule_type=RuleType.AMOUNT_THRESHOLD,
            parameters={"threshold": 1000.00, "currency": "EUR"},
            severity=AlertSeverity.HIGH,
        )
        # Transaction is USD, rule specifies EUR -> should not match
        assert evaluate_rule(rule_eur, base_transaction) is None

        rule_usd = RuleDefinition(
            id=uuid.uuid4(),
            name="USD Large Amount",
            rule_type=RuleType.AMOUNT_THRESHOLD,
            parameters={"threshold": 1000.00, "currency": "usd"},
            severity=AlertSeverity.HIGH,
        )
        assert evaluate_rule(rule_usd, base_transaction) is not None


class TestHighRiskCountryRule:
    def test_country_in_high_risk_list_triggers_match(self):
        txn = TransactionContext(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            amount=Decimal("100.00"),
            currency="USD",
            country="KP",
            merchant_category="groceries",
        )
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="Sanctioned Country Rule",
            rule_type=RuleType.HIGH_RISK_COUNTRY,
            parameters={"countries": ["IR", "KP", "SY"]},
            severity=AlertSeverity.CRITICAL,
        )
        match = evaluate_rule(rule, txn)
        assert match is not None
        assert match.severity == AlertSeverity.CRITICAL.value
        assert "matches high-risk country list" in match.explanation

    def test_country_case_insensitivity(self):
        txn = TransactionContext(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            amount=Decimal("100.00"),
            currency="USD",
            country="ir",
            merchant_category="groceries",
        )
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="Sanctioned Country Rule",
            rule_type=RuleType.HIGH_RISK_COUNTRY,
            parameters={"countries": ["IR", "KP"]},
            severity=AlertSeverity.CRITICAL,
        )
        match = evaluate_rule(rule, txn)
        assert match is not None

    def test_country_not_in_list_no_match(self, base_transaction):
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="Sanctioned Country Rule",
            rule_type=RuleType.HIGH_RISK_COUNTRY,
            parameters={"countries": ["IR", "KP"]},
            severity=AlertSeverity.CRITICAL,
        )
        assert evaluate_rule(rule, base_transaction) is None


class TestVelocityRule:
    def test_velocity_count_exceeded_triggers_match(self, base_transaction):
        velocity = VelocityContext(
            user_id=base_transaction.user_id,
            window_minutes=10,
            transaction_count=6,
            total_amount=Decimal("1200.00"),
        )
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="High Frequency Rule",
            rule_type=RuleType.VELOCITY,
            parameters={"max_count": 5, "window_minutes": 10},
            severity=AlertSeverity.MEDIUM,
        )
        match = evaluate_rule(rule, base_transaction, velocity=velocity)
        assert match is not None
        assert "count 6 >= limit 5" in match.explanation

    def test_velocity_amount_exceeded_triggers_match(self, base_transaction):
        velocity = VelocityContext(
            user_id=base_transaction.user_id,
            window_minutes=10,
            transaction_count=2,
            total_amount=Decimal("30000.00"),
        )
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="Velocity Amount Rule",
            rule_type=RuleType.VELOCITY,
            parameters={"max_amount": 25000.00},
            severity=AlertSeverity.HIGH,
        )
        match = evaluate_rule(rule, base_transaction, velocity=velocity)
        assert match is not None
        assert "total amount 30000.00 >= limit 25000.00" in match.explanation

    def test_velocity_within_limits_no_match(self, base_transaction):
        velocity = VelocityContext(
            user_id=base_transaction.user_id,
            window_minutes=10,
            transaction_count=2,
            total_amount=Decimal("500.00"),
        )
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="Velocity Rule",
            rule_type=RuleType.VELOCITY,
            parameters={"max_count": 5, "max_amount": 10000.00},
            severity=AlertSeverity.MEDIUM,
        )
        assert evaluate_rule(rule, base_transaction, velocity=velocity) is None

    def test_missing_velocity_context_returns_none(self, base_transaction):
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="Velocity Rule",
            rule_type=RuleType.VELOCITY,
            parameters={"max_count": 5},
            severity=AlertSeverity.MEDIUM,
        )
        assert evaluate_rule(rule, base_transaction, velocity=None) is None


class TestUserRiskLevelRule:
    def test_high_user_risk_score_triggers_match(self, base_transaction):
        risk_profile = RiskProfileSnapshot(
            user_id=base_transaction.user_id,
            risk_score=Decimal("0.8500"),
            total_alerts=3,
        )
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="High Risk Profile Rule",
            rule_type=RuleType.USER_RISK_LEVEL,
            parameters={"min_risk_score": 0.70},
            severity=AlertSeverity.HIGH,
        )
        match = evaluate_rule(rule, base_transaction, risk_profile=risk_profile)
        assert match is not None
        assert "User risk score 0.8500 meets or exceeds risk threshold 0.7000" in match.explanation

    def test_low_user_risk_score_no_match(self, base_transaction):
        risk_profile = RiskProfileSnapshot(
            user_id=base_transaction.user_id,
            risk_score=Decimal("0.2000"),
        )
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="High Risk Profile Rule",
            rule_type=RuleType.USER_RISK_LEVEL,
            parameters={"min_risk_score": 0.70},
            severity=AlertSeverity.HIGH,
        )
        assert evaluate_rule(rule, base_transaction, risk_profile=risk_profile) is None


class TestMerchantCategoryRule:
    def test_monitored_category_triggers_match(self):
        txn = TransactionContext(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            amount=Decimal("500.00"),
            currency="USD",
            country="US",
            merchant_category="gambling_casino",
        )
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="Gambling Category Rule",
            rule_type=RuleType.MERCHANT_CATEGORY,
            parameters={"categories": ["crypto", "gambling_casino", "weapons"]},
            severity=AlertSeverity.HIGH,
        )
        match = evaluate_rule(rule, txn)
        assert match is not None
        assert "matches monitored high-risk merchant categories" in match.explanation

    def test_normal_category_no_match(self, base_transaction):
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="High Risk MCC Rule",
            rule_type=RuleType.MERCHANT_CATEGORY,
            parameters={"categories": ["crypto", "weapons"]},
            severity=AlertSeverity.HIGH,
        )
        assert evaluate_rule(rule, base_transaction) is None


class TestEvaluateRulesCollection:
    def test_disabled_rule_is_ignored(self, base_transaction):
        rule = RuleDefinition(
            id=uuid.uuid4(),
            name="Disabled Rule",
            rule_type=RuleType.AMOUNT_THRESHOLD,
            parameters={"threshold": 100.00},
            severity=AlertSeverity.CRITICAL,
            enabled=False,
        )
        assert evaluate_rules([rule], base_transaction) == []

    def test_multiple_rules_evaluation(self, base_transaction):
        rule1 = RuleDefinition(
            id=uuid.uuid4(),
            name="Rule 1 Amount",
            rule_type=RuleType.AMOUNT_THRESHOLD,
            parameters={"threshold": 1000.00},
            severity=AlertSeverity.MEDIUM,
        )
        rule2 = RuleDefinition(
            id=uuid.uuid4(),
            name="Rule 2 Category",
            rule_type=RuleType.MERCHANT_CATEGORY,
            parameters={"categories": ["electronics"]},
            severity=AlertSeverity.LOW,
        )
        rule3 = RuleDefinition(
            id=uuid.uuid4(),
            name="Rule 3 Country",
            rule_type=RuleType.HIGH_RISK_COUNTRY,
            parameters={"countries": ["KP"]},
            severity=AlertSeverity.CRITICAL,
        )
        matches = evaluate_rules([rule1, rule2, rule3], base_transaction)
        assert len(matches) == 2
        assert {m.rule_name for m in matches} == {"Rule 1 Amount", "Rule 2 Category"}

    def test_rule_parameter_edge_cases(self, base_transaction):
        # Missing threshold
        r1 = RuleDefinition(
            id=uuid.uuid4(),
            name="No Threshold",
            rule_type=RuleType.AMOUNT_THRESHOLD,
            parameters={},
            severity=AlertSeverity.LOW,
        )
        assert evaluate_rule(r1, base_transaction) is None

        # Invalid threshold string
        r2 = RuleDefinition(
            id=uuid.uuid4(),
            name="Invalid Threshold",
            rule_type=RuleType.AMOUNT_THRESHOLD,
            parameters={"threshold": "invalid_num"},
            severity=AlertSeverity.LOW,
        )
        assert evaluate_rule(r2, base_transaction) is None

        # Greater-than operator
        r3 = RuleDefinition(
            id=uuid.uuid4(),
            name="Strict Greater",
            rule_type=RuleType.AMOUNT_THRESHOLD,
            parameters={"threshold": 1500.00, "operator": ">"},
            severity=AlertSeverity.LOW,
        )
        assert evaluate_rule(r3, base_transaction) is None  # 1500 is not > 1500

        # Invalid countries parameter
        r4 = RuleDefinition(
            id=uuid.uuid4(),
            name="Invalid Countries",
            rule_type=RuleType.HIGH_RISK_COUNTRY,
            parameters={"countries": 12345},
            severity=AlertSeverity.HIGH,
        )
        assert evaluate_rule(r4, base_transaction) is None

        # Invalid user risk threshold
        r5 = RuleDefinition(
            id=uuid.uuid4(),
            name="Invalid Risk Score",
            rule_type=RuleType.USER_RISK_LEVEL,
            parameters={"min_risk_score": "not_a_number"},
            severity=AlertSeverity.HIGH,
        )
        risk_profile = RiskProfileSnapshot(user_id=base_transaction.user_id, risk_score=Decimal("0.5"))
        assert evaluate_rule(r5, base_transaction, risk_profile=risk_profile) is None

        # Missing user risk threshold
        r6 = RuleDefinition(
            id=uuid.uuid4(),
            name="Missing Risk Score",
            rule_type=RuleType.USER_RISK_LEVEL,
            parameters={},
            severity=AlertSeverity.HIGH,
        )
        assert evaluate_rule(r6, base_transaction, risk_profile=risk_profile) is None

        # Invalid categories parameter
        r7 = RuleDefinition(
            id=uuid.uuid4(),
            name="Invalid Categories",
            rule_type=RuleType.MERCHANT_CATEGORY,
            parameters={"categories": "not-a-list"},
            severity=AlertSeverity.HIGH,
        )
        assert evaluate_rule(r7, base_transaction) is None
