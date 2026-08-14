import uuid
from django.db import models
from django.utils import timezone


class User(models.Model):
    """Simulated customer/account holder whose transactions are monitored."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, max_length=255)
    country = models.CharField(max_length=2, help_text="ISO-3166 alpha-2 country code")
    account_created_at = models.DateTimeField(default=timezone.now)
    is_seed_data = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        indexes = [
            models.Index(fields=['email'], name='idx_users_email'),
            models.Index(fields=['country'], name='idx_users_country'),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.email})"
