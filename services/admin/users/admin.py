from django.contrib import admin
from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'country', 'is_seed_data', 'created_at')
    list_filter = ('country', 'is_seed_data', 'created_at')
    search_fields = ('full_name', 'email')
    readonly_fields = ('id', 'created_at', 'updated_at')
