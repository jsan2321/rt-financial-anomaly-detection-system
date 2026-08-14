"""
Unit tests for DEMO_MODE Strategy Pattern isolation.
Tests NullDemoStrategy, DeterministicDemoStrategy overrides, and factory selection.
"""

from decimal import Decimal
import uuid
import pytest

from shared.models.enums import AlertSeverity
from services.processor.domain.demo_strategy import (
    DeterministicDemoStrategy,
    NullDemoStrategy,
    get_demo_strategy,
)
from services.processor.domain.schemas import (
    DetectionResult,
    TransactionContext,
)


@pytest.fixture
def benign_decision() -> DetectionResult:
    return DetectionResult(
        should_alert=False,
        severity=AlertSeverity.LOW,
        composite_risk_score=Decimal("0.1500"),
        rule_severity_score=Decimal("0.0000"),
        ml_anomaly_score=Decimal("0.2000"),
        user_risk_score=Decimal("0.0000"),
        rule_matches=[],
        risk_profile_snapshot={},
        is_demo=False,
    )


class TestNullDemoStrategy:
    def test_null_strategy_leaves_demo_transaction_unmodified(self, benign_decision):
        txn = TransactionContext(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            amount=Decimal("50.00"),
            currency="USD",
            country="US",
            merchant_category="groceries",
            metadata={"demo_scenario": "velocity_burst"},
        )
        strategy = NullDemoStrategy()
        overridden = strategy.override(txn, benign_decision)

        # In null strategy, demo_scenario in metadata does NOT trigger an alert
        assert overridden.should_alert is False
        assert overridden.is_demo is False
        assert overridden.composite_risk_score == Decimal("0.1500")


class TestDeterministicDemoStrategy:
    def test_demo_scenario_metadata_forces_critical_demo_alert(self, benign_decision):
        txn = TransactionContext(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            amount=Decimal("50.00"),
            currency="USD",
            country="US",
            merchant_category="groceries",
            metadata={"demo_scenario": "sanction_evasion_test"},
        )
        strategy = DeterministicDemoStrategy()
        overridden = strategy.override(txn, benign_decision)

        assert overridden.should_alert is True
        assert overridden.severity == AlertSeverity.CRITICAL
        assert overridden.is_demo is True
        assert overridden.composite_risk_score == Decimal("1.0000")
        assert "DEMO_MODE forced alert" in overridden.explanation
        assert any(m.rule_type == "DEMO_SCENARIO" for m in overridden.rule_matches)

    def test_non_demo_transaction_remains_unmodified_in_demo_strategy(self, benign_decision):
        txn = TransactionContext(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            amount=Decimal("50.00"),
            currency="USD",
            country="US",
            merchant_category="groceries",
            metadata={},  # No demo_scenario
        )
        strategy = DeterministicDemoStrategy()
        overridden = strategy.override(txn, benign_decision)

        assert overridden.should_alert is False
        assert overridden.is_demo is False
        assert overridden.composite_risk_score == Decimal("0.1500")


class TestDemoStrategyFactory:
    def test_factory_returns_null_strategy_by_default(self):
        strategy = get_demo_strategy(demo_mode=False)
        assert isinstance(strategy, NullDemoStrategy)

    def test_factory_returns_deterministic_strategy_when_enabled(self):
        strategy = get_demo_strategy(demo_mode=True)
        assert isinstance(strategy, DeterministicDemoStrategy)
