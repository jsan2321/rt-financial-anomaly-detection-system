"""
Django REST Framework serializers for internal control plane endpoints.
"""

from rest_framework import serializers

from audit.models import AuditLog
from fraud_rules.models import FraudRule
from surveillance.models import Alert, RiskProfile, Transaction
from users.models import User


class FraudRuleSerializer(serializers.ModelSerializer):
    """Serializer for FraudRule models."""

    class Meta:
        model = FraudRule
        fields = [
            'id',
            'name',
            'rule_type',
            'parameters',
            'severity',
            'enabled',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class AuditLogSerializer(serializers.ModelSerializer):
    """Serializer for AuditLog trail."""

    class Meta:
        model = AuditLog
        fields = [
            'id',
            'actor',
            'action',
            'entity_type',
            'entity_id',
            'before',
            'after',
            'correlation_id',
            'created_at',
        ]
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User entities."""

    class Meta:
        model = User
        fields = [
            'id',
            'full_name',
            'email',
            'country',
            'account_created_at',
            'is_seed_data',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class AlertReadOnlySerializer(serializers.ModelSerializer):
    """Read-only serializer for Alert entities."""

    class Meta:
        model = Alert
        fields = [
            'id',
            'transaction_id',
            'user_id',
            'status',
            'severity',
            'composite_risk_score',
            'ml_anomaly_score',
            'rule_matches',
            'risk_profile_snapshot',
            'is_demo',
            'resolved_by',
            'resolved_at',
            'resolution_reason',
            'escalated_email_at',
            'escalated_slack_at',
            'correlation_id',
            'created_at',
        ]
        read_only_fields = fields


class TransactionReadOnlySerializer(serializers.ModelSerializer):
    """Read-only serializer for Transaction entities."""

    class Meta:
        model = Transaction
        fields = [
            'id',
            'user_id',
            'amount',
            'currency',
            'country',
            'merchant_category',
            'status',
            'idempotency_key',
            'metadata',
            'correlation_id',
            'processed_at',
            'created_at',
        ]
        read_only_fields = fields


class RiskProfileReadOnlySerializer(serializers.ModelSerializer):
    """Read-only serializer for RiskProfile entities."""

    class Meta:
        model = RiskProfile
        fields = [
            'user_id',
            'risk_score',
            'total_alerts',
            'false_positive_count',
            'last_recalculated_at',
        ]
        read_only_fields = fields
