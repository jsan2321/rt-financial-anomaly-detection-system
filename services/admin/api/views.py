"""
Django REST Framework Read-Only ViewSets for internal control plane endpoints.
"""

from rest_framework import viewsets

from audit.models import AuditLog
from fraud_rules.models import FraudRule
from surveillance.models import Alert, RiskProfile, Transaction
from users.models import User
from .serializers import (
    AlertReadOnlySerializer,
    AuditLogSerializer,
    FraudRuleSerializer,
    RiskProfileReadOnlySerializer,
    TransactionReadOnlySerializer,
    UserSerializer,
)


class FraudRuleReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only API endpoint for Fraud Rules.
    Used by Processor and external surveillance tooling.
    """
    queryset = FraudRule.objects.all().order_by('-created_at')
    serializer_class = FraudRuleSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        enabled_param = self.request.query_params.get('enabled')
        if enabled_param is not None:
            is_enabled = enabled_param.lower() in ('true', '1')
            qs = qs.filter(enabled=is_enabled)
        rule_type = self.request.query_params.get('rule_type')
        if rule_type:
            qs = qs.filter(rule_type=rule_type)
        severity = self.request.query_params.get('severity')
        if severity:
            qs = qs.filter(severity=severity)
        return qs


class AuditLogReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only API endpoint for Audit Trail inspection.
    """
    queryset = AuditLog.objects.all().order_by('-created_at')
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        action = self.request.query_params.get('action')
        if action:
            qs = qs.filter(action=action)
        entity_type = self.request.query_params.get('entity_type')
        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        entity_id = self.request.query_params.get('entity_id')
        if entity_id:
            qs = qs.filter(entity_id=entity_id)
        actor = self.request.query_params.get('actor')
        if actor:
            qs = qs.filter(actor=actor)
        return qs


class UserReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only API endpoint for Customer Accounts.
    """
    queryset = User.objects.all().order_by('-created_at')
    serializer_class = UserSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        country = self.request.query_params.get('country')
        if country:
            qs = qs.filter(country=country.upper())
        is_seed = self.request.query_params.get('is_seed_data')
        if is_seed is not None:
            qs = qs.filter(is_seed_data=is_seed.lower() in ('true', '1'))
        return qs


class AlertReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only API endpoint for detected Alerts.
    """
    queryset = Alert.objects.all().order_by('-created_at')
    serializer_class = AlertReadOnlySerializer


class TransactionReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only API endpoint for Transactions.
    """
    queryset = Transaction.objects.all().order_by('-created_at')
    serializer_class = TransactionReadOnlySerializer


class RiskProfileReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only API endpoint for Customer Risk Profiles.
    """
    queryset = RiskProfile.objects.all().order_by('-last_recalculated_at')
    serializer_class = RiskProfileReadOnlySerializer
