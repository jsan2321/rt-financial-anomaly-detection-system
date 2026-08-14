"""
Django Admin interface for FraudRule management with automated audit logging.
"""

from typing import Any, Dict

from django.contrib import admin

from audit.models import AuditLog
from .models import FraudRule


def get_rule_snapshot(rule: FraudRule) -> Dict[str, Any]:
    """Serializes a FraudRule instance into a dictionary for audit logging."""
    return {
        "id": str(rule.id),
        "name": rule.name,
        "rule_type": rule.rule_type,
        "parameters": rule.parameters,
        "severity": rule.severity,
        "enabled": rule.enabled,
    }


@admin.register(FraudRule)
class FraudRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'rule_type', 'severity', 'enabled', 'created_at', 'updated_at')
    list_filter = ('rule_type', 'severity', 'enabled')
    search_fields = ('name',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('id', 'name', 'rule_type', 'severity', 'enabled'),
        }),
        ('Rule Parameters', {
            'fields': ('parameters',),
            'description': 'JSON configuration defining thresholds, country codes, or velocity limits.',
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request: Any, obj: FraudRule, form: Any, change: bool) -> None:
        """
        Saves the FraudRule instance and records an AuditLog entry.
        """
        actor = request.user.username if (hasattr(request, 'user') and request.user.is_authenticated) else 'django_admin'
        before_state = None

        if change:
            try:
                prev_rule = FraudRule.objects.get(pk=obj.pk)
                before_state = get_rule_snapshot(prev_rule)
            except FraudRule.DoesNotExist:
                before_state = None

        super().save_model(request, obj, form, change)

        after_state = get_rule_snapshot(obj)
        action = "RULE_UPDATE" if change else "RULE_CREATE"

        AuditLog.objects.create(
            actor=actor,
            action=action,
            entity_type="FraudRule",
            entity_id=str(obj.id),
            before=before_state,
            after=after_state,
        )

    def delete_model(self, request: Any, obj: FraudRule) -> None:
        """
        Deletes the FraudRule instance and records an AuditLog entry.
        """
        actor = request.user.username if (hasattr(request, 'user') and request.user.is_authenticated) else 'django_admin'
        before_state = get_rule_snapshot(obj)
        rule_id = str(obj.id)

        super().delete_model(request, obj)

        AuditLog.objects.create(
            actor=actor,
            action="RULE_DELETE",
            entity_type="FraudRule",
            entity_id=rule_id,
            before=before_state,
            after=None,
        )

    def delete_queryset(self, request: Any, queryset: Any) -> None:
        """
        Deletes multiple FraudRule instances and records an AuditLog entry for each.
        """
        actor = request.user.username if (hasattr(request, 'user') and request.user.is_authenticated) else 'django_admin'
        for obj in queryset:
            before_state = get_rule_snapshot(obj)
            AuditLog.objects.create(
                actor=actor,
                action="RULE_DELETE",
                entity_type="FraudRule",
                entity_id=str(obj.id),
                before=before_state,
                after=None,
            )
        super().delete_queryset(request, queryset)
