import uuid
from django.db import models
from django.utils import timezone


class FraudRule(models.Model):
    """Deterministic fraud rule evaluated by Processor service."""

    RULE_TYPE_CHOICES = [
        ('AMOUNT_THRESHOLD', 'Amount Threshold'),
        ('HIGH_RISK_COUNTRY', 'High Risk Country'),
        ('VELOCITY', 'Transaction Velocity'),
        ('USER_RISK_LEVEL', 'User Risk Level'),
        ('MERCHANT_CATEGORY', 'Merchant Category'),
    ]

    SEVERITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    rule_type = models.CharField(max_length=64, choices=RULE_TYPE_CHOICES)
    parameters = models.JSONField(default=dict, help_text="Rule evaluation parameters in JSON format")
    severity = models.CharField(max_length=32, choices=SEVERITY_CHOICES)
    enabled = models.BooleanField(default=True, help_text="Active status for rule evaluation")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fraud_rules'
        verbose_name = 'Fraud Rule'
        verbose_name_plural = 'Fraud Rules'
        indexes = [
            models.Index(fields=['enabled'], name='idx_fraud_rules_enabled', condition=models.Q(enabled=True)),
        ]

    def __str__(self):
        return f"{self.name} [{self.rule_type}] ({self.severity})"
