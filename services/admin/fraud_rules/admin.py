from django.contrib import admin
from .models import FraudRule


@admin.register(FraudRule)
class FraudRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'rule_type', 'severity', 'enabled', 'created_at')
    list_filter = ('rule_type', 'severity', 'enabled')
    search_fields = ('name',)
    readonly_fields = ('id', 'created_at', 'updated_at')
