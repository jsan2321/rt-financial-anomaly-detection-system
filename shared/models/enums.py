"""
Domain enums for transaction statuses, alert lifecycles, and rule types.
"""

from enum import Enum


class TransactionStatus(str, Enum):
    """Processing status lifecycle of a financial transaction."""
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    PROCESSING_FAILED = "PROCESSING_FAILED"


class AlertStatus(str, Enum):
    """
    Lifecycle status of an anomaly detection alert.
    Non-terminal: PENDING, ESCALATED_EMAIL, ESCALATED_SLACK
    Terminal: APPROVED, BLOCKED, FALSE_POSITIVE
    """
    PENDING = "PENDING"
    ESCALATED_EMAIL = "ESCALATED_EMAIL"
    ESCALATED_SLACK = "ESCALATED_SLACK"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    FALSE_POSITIVE = "FALSE_POSITIVE"

    @property
    def is_terminal(self) -> bool:
        return self in (
            AlertStatus.APPROVED,
            AlertStatus.BLOCKED,
            AlertStatus.FALSE_POSITIVE,
        )

    @property
    def is_escalated(self) -> bool:
        return self in (
            AlertStatus.ESCALATED_EMAIL,
            AlertStatus.ESCALATED_SLACK,
        )


class AlertSeverity(str, Enum):
    """Severity classification for fraud alerts."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RuleType(str, Enum):
    """Deterministic rule categories supported by the detection engine."""
    AMOUNT_THRESHOLD = "AMOUNT_THRESHOLD"
    HIGH_RISK_COUNTRY = "HIGH_RISK_COUNTRY"
    VELOCITY = "VELOCITY"
    USER_RISK_LEVEL = "USER_RISK_LEVEL"
    MERCHANT_CATEGORY = "MERCHANT_CATEGORY"


class OutboxStatus(str, Enum):
    """Dispatch status of outbox relay records."""
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    DEAD_LETTERED = "DEAD_LETTERED"
