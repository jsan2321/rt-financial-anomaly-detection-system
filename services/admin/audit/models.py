import uuid
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    """Append-only audit trail recording significant system mutations and actions."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.CharField(max_length=255, help_text="User, system service, or agent identity")
    action = models.CharField(max_length=64, help_text="Action performed, e.g., RULE_UPDATE, ALERT_APPROVE")
    entity_type = models.CharField(max_length=64, help_text="Type of entity affected, e.g., FraudRule, Alert")
    entity_id = models.CharField(max_length=255, help_text="Identifier of the affected entity")
    before = models.JSONField(null=True, blank=True, help_text="State prior to mutation")
    after = models.JSONField(null=True, blank=True, help_text="State following mutation")
    correlation_id = models.UUIDField(null=True, blank=True, help_text="Distributed trace correlation ID")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'audit_logs'
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id'], name='idx_audit_logs_entity'),
            models.Index(fields=['created_at'], name='idx_audit_logs_created_at'),
            models.Index(fields=['correlation_id'], name='idx_audit_logs_correlation_id'),
        ]

    def __str__(self):
        return f"[{self.created_at.isoformat()}] {self.actor} - {self.action} on {self.entity_type}:{self.entity_id}"
