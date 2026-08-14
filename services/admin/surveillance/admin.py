"""
Read-only Django Admin registrations for unmanaged domain tables.
"""

from typing import Any
from django.contrib import admin
from .models import Alert, RiskProfile, Transaction


class ReadOnlyAdminMixin:
    """Disables all create, edit, and delete permissions."""

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(Transaction)
class TransactionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'user_id', 'amount', 'currency', 'country', 'merchant_category', 'status', 'created_at')
    list_filter = ('status', 'currency', 'country', 'created_at')
    search_fields = ('id', 'user_id', 'idempotency_key', 'correlation_id')
    readonly_fields = [f.name for f in Transaction._meta.fields]


@admin.register(Alert)
class AlertAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        'id',
        'severity',
        'status',
        'composite_risk_score',
        'ml_anomaly_score',
        'is_demo',
        'resolved_by',
        'created_at',
    )
    list_filter = ('status', 'severity', 'is_demo', 'created_at')
    search_fields = ('id', 'transaction_id', 'correlation_id', 'resolved_by')
    readonly_fields = [f.name for f in Alert._meta.fields]


@admin.register(RiskProfile)
class RiskProfileAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ('user_id', 'risk_score', 'total_alerts', 'false_positive_count', 'last_recalculated_at')
    list_filter = ('last_recalculated_at',)
    search_fields = ('user_id',)
    readonly_fields = [f.name for f in RiskProfile._meta.fields]
