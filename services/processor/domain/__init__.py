"""
Domain package for RT-FADS Processor detection engine.
Exports schemas, rules engine, ML scoring, composite scoring, and demo strategies.
"""

from .composite_scoring import (
    calculate_rule_severity_score,
    compute_composite_risk_score,
    compute_detection_decision,
    determine_alert_severity,
    SEVERITY_VALUES,
)
from .demo_strategy import (
    DemoOverrideStrategy,
    DeterministicDemoStrategy,
    NullDemoStrategy,
    get_demo_strategy,
)
from .ml_model import (
    MLAnomalyScorer,
    MLMetadata,
    MLModelLoadError,
)
from .rules import (
    evaluate_rule,
    evaluate_rules,
)
from .schemas import (
    DetectionResult,
    RiskProfileSnapshot,
    RuleDefinition,
    RuleMatch,
    ScoringWeights,
    TransactionContext,
    VelocityContext,
)

__all__ = [
    "calculate_rule_severity_score",
    "compute_composite_risk_score",
    "compute_detection_decision",
    "determine_alert_severity",
    "SEVERITY_VALUES",
    "DemoOverrideStrategy",
    "DeterministicDemoStrategy",
    "NullDemoStrategy",
    "get_demo_strategy",
    "MLAnomalyScorer",
    "MLMetadata",
    "MLModelLoadError",
    "evaluate_rule",
    "evaluate_rules",
    "DetectionResult",
    "RiskProfileSnapshot",
    "RuleDefinition",
    "RuleMatch",
    "ScoringWeights",
    "TransactionContext",
    "VelocityContext",
]
