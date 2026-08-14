"""
Unmanaged Django models representing domain entities owned and migrated by Alembic.
These models are strictly read-only within the Django Admin service.
"""

import uuid
from django.db import models


class Transaction(models.Model):
    """Read-only view of ingested financial transactions."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField(editable=False)
    amount = models.DecimalField(max_digits=14, decimal_places=2, editable=False)
    currency = models.CharField(max_length=3, editable=False)
    country = models.CharField(max_length=2, editable=False)
    merchant_category = models.CharField(max_length=100, editable=False)
    status = models.CharField(max_length=32, editable=False)
    idempotency_key = models.CharField(max_length=255, editable=False)
    metadata = models.JSONField(null=True, blank=True, editable=False, db_column='metadata')
    correlation_id = models.UUIDField(editable=False)
    processed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(editable=False)

    class Meta:
        managed = False
        db_table = 'transactions'
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Txn {self.id} - {self.amount} {self.currency} [{self.status}]"


class Alert(models.Model):
    """Read-only view of detected anomaly alerts."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction_id = models.UUIDField(editable=False)
    user_id = models.UUIDField(editable=False)
    status = models.CharField(max_length=32, editable=False)
    severity = models.CharField(max_length=32, editable=False)
    composite_risk_score = models.DecimalField(max_digits=5, decimal_places=4, editable=False)
    ml_anomaly_score = models.DecimalField(max_digits=5, decimal_places=4, editable=False)
    rule_matches = models.JSONField(default=list, editable=False, db_column='rule_matches')
    risk_profile_snapshot = models.JSONField(default=dict, editable=False, db_column='risk_profile_snapshot')
    is_demo = models.BooleanField(default=False, editable=False)
    resolved_by = models.CharField(max_length=255, null=True, blank=True, editable=False)
    resolved_at = models.DateTimeField(null=True, blank=True, editable=False)
    resolution_reason = models.TextField(null=True, blank=True, editable=False)
    escalated_email_at = models.DateTimeField(null=True, blank=True, editable=False)
    escalated_slack_at = models.DateTimeField(null=True, blank=True, editable=False)
    correlation_id = models.UUIDField(editable=False)
    created_at = models.DateTimeField(editable=False)

    class Meta:
        managed = False
        db_table = 'alerts'
        verbose_name = 'Alert'
        verbose_name_plural = 'Alerts'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Alert {self.id} - {self.severity} ({self.status}) Score: {self.composite_risk_score:.2f}"


class RiskProfile(models.Model):
    """Read-only view of customer risk profiles maintained by Processor."""
    user_id = models.UUIDField(primary_key=True, editable=False)
    risk_score = models.DecimalField(max_digits=5, decimal_places=4, editable=False)
    total_alerts = models.IntegerField(default=0, editable=False, db_column='total_alerts')
    false_positive_count = models.IntegerField(default=0, editable=False)
    last_recalculated_at = models.DateTimeField(editable=False, db_column='last_recalculated_at')

    class Meta:
        managed = False
        db_table = 'risk_profiles'
        verbose_name = 'Risk Profile'
        verbose_name_plural = 'Risk Profiles'
        ordering = ['-last_recalculated_at']

    def __str__(self) -> str:
        return f"RiskProfile User:{self.user_id} - Score: {self.risk_score:.2f} (Alerts: {self.total_alerts})"
