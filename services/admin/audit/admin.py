from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'entity_type', 'entity_id', 'correlation_id')
    list_filter = ('action', 'entity_type', 'created_at')
    search_fields = ('actor', 'entity_id', 'correlation_id')
    readonly_fields = ('id', 'actor', 'action', 'entity_type', 'entity_id', 'before', 'after', 'correlation_id', 'created_at')

    def has_add_permission(self, request):
        # Audit logs are append-only by system services
        return False

    def has_delete_permission(self, request, obj=None):
        # Audit logs cannot be deleted
        return False

    def has_change_permission(self, request, obj=None):
        # Audit logs cannot be modified
        return False
