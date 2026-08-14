"""
Unit tests for Django Admin read-only permissions and unmanaged model boundaries.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure services/admin is on sys.path
admin_service_path = Path(__file__).resolve().parents[2] / "services" / "admin"
if str(admin_service_path) not in sys.path:
    sys.path.insert(0, str(admin_service_path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from audit.admin import AuditLogAdmin
from audit.models import AuditLog
from surveillance.admin import AlertAdmin, RiskProfileAdmin, TransactionAdmin
from surveillance.models import Alert, RiskProfile, Transaction


@pytest.fixture
def admin_site() -> AdminSite:
    return AdminSite()


@pytest.fixture
def mock_request() -> MagicMock:
    rf = RequestFactory()
    request = rf.get("/admin/")
    user = MagicMock()
    user.is_authenticated = True
    user.is_superuser = True
    request.user = user
    return request


def test_unmanaged_model_flags() -> None:
    """Alembic-owned domain models must be configured as unmanaged in Django."""
    assert Transaction._meta.managed is False
    assert Alert._meta.managed is False
    assert RiskProfile._meta.managed is False


def test_audit_log_admin_readonly_permissions(admin_site: AdminSite, mock_request: MagicMock) -> None:
    admin_instance = AuditLogAdmin(AuditLog, admin_site)
    assert admin_instance.has_add_permission(mock_request) is False
    assert admin_instance.has_change_permission(mock_request) is False
    assert admin_instance.has_delete_permission(mock_request) is False


def test_transaction_admin_readonly_permissions(admin_site: AdminSite, mock_request: MagicMock) -> None:
    admin_instance = TransactionAdmin(Transaction, admin_site)
    assert admin_instance.has_add_permission(mock_request) is False
    assert admin_instance.has_change_permission(mock_request) is False
    assert admin_instance.has_delete_permission(mock_request) is False


def test_alert_admin_readonly_permissions(admin_site: AdminSite, mock_request: MagicMock) -> None:
    admin_instance = AlertAdmin(Alert, admin_site)
    assert admin_instance.has_add_permission(mock_request) is False
    assert admin_instance.has_change_permission(mock_request) is False
    assert admin_instance.has_delete_permission(mock_request) is False


def test_risk_profile_admin_readonly_permissions(admin_site: AdminSite, mock_request: MagicMock) -> None:
    admin_instance = RiskProfileAdmin(RiskProfile, admin_site)
    assert admin_instance.has_add_permission(mock_request) is False
    assert admin_instance.has_change_permission(mock_request) is False
    assert admin_instance.has_delete_permission(mock_request) is False
