"""
DEMO_MODE Strategy Pattern implementation for RT-FADS.
Cleanly isolates synthetic demo overrides from production business logic.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

from shared.models.enums import AlertSeverity

from .schemas import DetectionResult, RuleMatch, TransactionContext


class DemoOverrideStrategy(ABC):
    """Abstract Strategy interface for demo alert overriding."""

    @abstractmethod
    def override(
        self,
        transaction: TransactionContext,
        decision: DetectionResult,
    ) -> DetectionResult:
        """
        Applies optional demo overrides to a pure detection decision.
        Must be called exactly once as the final step in the decision pipeline.
        """
        pass


class NullDemoStrategy(DemoOverrideStrategy):
    """Production mode no-op strategy. Never overrides any decisions."""

    def override(
        self,
        transaction: TransactionContext,
        decision: DetectionResult,
    ) -> DetectionResult:
        return decision


class DeterministicDemoStrategy(DemoOverrideStrategy):
    """
    Demo mode strategy that forces CRITICAL alerts for transactions tagged with
    `metadata.demo_scenario`. All other transactions remain unmodified.
    """

    def override(
        self,
        transaction: TransactionContext,
        decision: DetectionResult,
    ) -> DetectionResult:
        scenario = transaction.metadata.get("demo_scenario")
        if not scenario:
            return decision

        demo_scenario_name = str(scenario)

        # Create demo rule match explaining the forced alert
        demo_match = RuleMatch(
            rule_id="00000000-0000-0000-0000-000000000000",
            rule_name=f"Demo Scenario: {demo_scenario_name}",
            rule_type="DEMO_SCENARIO",
            severity=AlertSeverity.CRITICAL.value,
            explanation=f"DEMO_MODE override forced CRITICAL alert for scenario '{demo_scenario_name}'",
            parameters_snapshot={"demo_scenario": demo_scenario_name},
            matched_at=datetime.now(timezone.utc),
        )

        existing_matches: List[RuleMatch] = list(decision.rule_matches)
        existing_matches.append(demo_match)

        return DetectionResult(
            should_alert=True,
            severity=AlertSeverity.CRITICAL,
            composite_risk_score=Decimal("1.0000"),
            rule_severity_score=Decimal("1.0000"),
            ml_anomaly_score=decision.ml_anomaly_score,
            user_risk_score=decision.user_risk_score,
            rule_matches=existing_matches,
            risk_profile_snapshot=decision.risk_profile_snapshot,
            is_demo=True,
            explanation=f"DEMO_MODE forced alert for scenario: {demo_scenario_name}",
        )


def get_demo_strategy(demo_mode: bool = False) -> DemoOverrideStrategy:
    """
    Strategy factory selecting NullDemoStrategy or DeterministicDemoStrategy
    based on the startup DEMO_MODE setting.
    """
    if demo_mode:
        return DeterministicDemoStrategy()
    return NullDemoStrategy()
