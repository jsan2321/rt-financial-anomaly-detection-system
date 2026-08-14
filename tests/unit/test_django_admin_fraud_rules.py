"""
Unit tests for Django Admin FraudRule mutations and automated AuditLog tracking.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock
import uuid

import pytest

# Ensure services/admin is on sys.path for Django module resolution
admin_service_path = Path(__file__).resolve().parents[2] / "services" / "admin"
if str(admin_service_path) not in sys.path:
    sys.path.insert(0, str(admin_service_path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.test import RequestFactory

from audit.models import AuditLog
from fraud_rules.admin import FraudRuleAdmin, get_rule_snapshot
from fraud_rules.models import FraudRule


@pytest.fixture(scope="session", autouse=True)
def setup_django_db() -> None:
    """Initializes in-memory database schema for Django test suite."""
    call_command("migrate", verbosity=0, interactive=False)


@pytest.fixture
def admin_site() -> AdminSite:
    return AdminSite()


@pytest.fixture
def rule_admin(admin_site: AdminSite) -> FraudRuleAdmin:
    return FraudRuleAdmin(FraudRule, admin_site)


@pytest.fixture
def mock_request() -> MagicMock:
    rf = RequestFactory()
    request = rf.get("/admin/fraud_rules/fraudrule/")
    user = MagicMock()
    user.is_authenticated = True
    user.username = "lead_fraud_analyst"
    request.user = user
    return request


def test_rule_snapshot_serialization() -> None:
    rule = FraudRule(
        id=uuid.uuid4(),
        name="High Amount Rule",
        rule_type="AMOUNT_THRESHOLD",
        parameters={"threshold": 10000.0},
        severity="CRITICAL",
        enabled=True,
    )
    snapshot = get_rule_snapshot(rule)
    assert snapshot["id"] == str(rule.id)
    assert snapshot["name"] == "High Amount Rule"
    assert snapshot["rule_type"] == "AMOUNT_THRESHOLD"
    assert snapshot["parameters"] == {"threshold": 10000.0}
    assert snapshot["severity"] == "CRITICAL"
    assert snapshot["enabled"] is True


def test_fraud_rule_admin_save_model_create(
    rule_admin: FraudRuleAdmin,
    mock_request: MagicMock,
) -> None:
    rule = FraudRule(
        name="New Velocity Rule",
        rule_type="VELOCITY",
        parameters={"max_count": 5, "window_minutes": 10},
        severity="HIGH",
        enabled=True,
    )

    initial_audit_count = AuditLog.objects.filter(entity_type="FraudRule").count()

    rule_admin.save_model(mock_request, rule, form=MagicMock(), change=False)

    assert rule.pk is not None
    assert AuditLog.objects.filter(entity_type="FraudRule").count() == initial_audit_count + 1

    latest_audit = AuditLog.objects.filter(entity_type="FraudRule").latest("created_at")
    assert latest_audit.action == "RULE_CREATE"
    assert latest_audit.actor == "lead_fraud_analyst"
    assert latest_audit.entity_id == str(rule.id)
    assert latest_audit.before is None
    assert latest_audit.after["name"] == "New Velocity Rule"
    assert latest_audit.after["severity"] == "HIGH"


def test_fraud_rule_admin_save_model_update(
    rule_admin: FraudRuleAdmin,
    mock_request: MagicMock,
) -> None:
    # 1. Create initial rule in DB
    rule = FraudRule.objects.create(
        name="Country Restriction Rule",
        rule_type="HIGH_RISK_COUNTRY",
        parameters={"countries": ["XX", "YY"]},
        severity="MEDIUM",
        enabled=True,
    )

    # 2. Modify rule attributes
    rule.severity = "CRITICAL"
    rule.parameters = {"countries": ["XX", "YY", "ZZ"]}

    initial_audit_count = AuditLog.objects.filter(entity_type="FraudRule").count()

    rule_admin.save_model(mock_request, rule, form=MagicMock(), change=True)

    assert AuditLog.objects.filter(entity_type="FraudRule").count() == initial_audit_count + 1

    latest_audit = AuditLog.objects.filter(entity_type="FraudRule").latest("created_at")
    assert latest_audit.action == "RULE_UPDATE"
    assert latest_audit.actor == "lead_fraud_analyst"
    assert latest_audit.entity_id == str(rule.id)
    assert latest_audit.before["severity"] == "MEDIUM"
    assert latest_audit.after["severity"] == "CRITICAL"
    assert "ZZ" in latest_audit.after["parameters"]["countries"]


def test_fraud_rule_admin_delete_model(
    rule_admin: FraudRuleAdmin,
    mock_request: MagicMock,
) -> None:
    rule = FraudRule.objects.create(
        name="Deprecated Rule",
        rule_type="AMOUNT_THRESHOLD",
        parameters={"threshold": 500.0},
        severity="LOW",
        enabled=False,
    )
    rule_id = str(rule.id)

    rule_admin.delete_model(mock_request, rule)

    assert not FraudRule.objects.filter(id=rule_id).exists()

    latest_audit = AuditLog.objects.filter(entity_type="FraudRule").latest("created_at")
    assert latest_audit.action == "RULE_DELETE"
    assert latest_audit.actor == "lead_fraud_analyst"
    assert latest_audit.entity_id == rule_id
    assert latest_audit.before["name"] == "Deprecated Rule"
    assert latest_audit.after is None


def test_fraud_rule_admin_delete_queryset(
    rule_admin: FraudRuleAdmin,
    mock_request: MagicMock,
) -> None:
    rule1 = FraudRule.objects.create(
        name="Batch Rule 1",
        rule_type="MERCHANT_CATEGORY",
        parameters={"categories": ["gambling"]},
        severity="HIGH",
        enabled=True,
    )
    rule2 = FraudRule.objects.create(
        name="Batch Rule 2",
        rule_type="MERCHANT_CATEGORY",
        parameters={"categories": ["crypto"]},
        severity="HIGH",
        enabled=True,
    )

    qs = FraudRule.objects.filter(id__in=[rule1.id, rule2.id])
    initial_audit_count = AuditLog.objects.filter(entity_type="FraudRule").count()

    rule_admin.delete_queryset(mock_request, qs)

    assert not FraudRule.objects.filter(id__in=[rule1.id, rule2.id]).exists()
    assert AuditLog.objects.filter(entity_type="FraudRule").count() == initial_audit_count + 2
