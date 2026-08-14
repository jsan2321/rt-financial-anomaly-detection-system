"""
Event types and stream topic constants for RT-FADS event-driven architecture.
"""

# Redis Streams Names
STREAM_TRANSACTIONS = "stream:transactions"
STREAM_ALERTS = "stream:alerts"
STREAM_ESCALATIONS = "stream:escalations"
STREAM_COMPENSATION = "stream:compensation"
STREAM_DLQ_PREFIX = "stream:dlq"

# Redis Pub/Sub Channels (Ephemeral local fan-out ONLY)
PUBSUB_NOTIFICATIONS = "ws:notifications"

# Consumer Group Names
CG_PROCESSOR = "processor-group"
CG_PROCESSOR_COMPENSATION = "processor-compensation-group"
CG_GATEWAY_NOTIFY = "gateway-notify-group"

# Event Type Identifiers
EVENT_TRANSACTION_CREATED = "transaction.created"
EVENT_ALERT_CREATED = "alert.created"
EVENT_ALERT_APPROVED = "alert.approved"
EVENT_ALERT_BLOCKED = "alert.blocked"
EVENT_ALERT_FALSE_POSITIVE = "alert.false_positive"
EVENT_ESCALATION_EMAIL_REQUESTED = "escalation.email.requested"
EVENT_ESCALATION_SLACK_REQUESTED = "escalation.slack.requested"
EVENT_RISK_PROFILE_RECALCULATE = "risk_profile.recalculate"

# Supported Event Versions
DEFAULT_EVENT_VERSION = "1.0"
