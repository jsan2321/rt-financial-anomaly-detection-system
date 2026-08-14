"""
Unit tests for Django REST Framework read-only control plane APIs.
"""

import os
import sys
from pathlib import Path
import uuid

import pytest

# Ensure services/admin is on sys.path
admin_service_path = Path(__file__).resolve().parents[2] / "services" / "admin"
if str(admin_service_path) not in sys.path:
    sys.path.insert(0, str(admin_service_path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.core.management import call_command
from django.db import connection
from rest_framework.test import APIClient

from audit.models import AuditLog
from fraud_rules.models import FraudRule
from surveillance.models import Alert, RiskProfile, Transaction
from users.models import User


@pytest.fixture(scope="session", autouse=True)
def setup_django_db() -> None:
    """Initializes in-memory database schema for Django test suite."""
    call_command("migrate", verbosity=0, interactive=False)
    with connection.schema_editor() as editor:
        editor.create_model(Transaction)
        editor.create_model(Alert)
        editor.create_model(RiskProfile)


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()



def test_drf_fraud_rules_list_and_retrieve(api_client: APIClient) -> None:
    rule = FraudRule.objects.create(
        name="API Test Rule",
        rule_type="AMOUNT_THRESHOLD",
        parameters={"threshold": 25000.0},
        severity="CRITICAL",
        enabled=True,
    )

    # List endpoint
    res_list = api_client.get("/api/admin/fraud-rules/")
    assert res_list.status_code == 200
    results = res_list.data.get("results", res_list.data)
    assert any(r["id"] == str(rule.id) for r in results)

    # Retrieve endpoint
    res_detail = api_client.get(f"/api/admin/fraud-rules/{rule.id}/")
    assert res_detail.status_code == 200
    assert res_detail.data["name"] == "API Test Rule"
    assert res_detail.data["severity"] == "CRITICAL"


def test_drf_fraud_rules_filter_by_enabled(api_client: APIClient) -> None:
    FraudRule.objects.create(
        name="Enabled Rule",
        rule_type="AMOUNT_THRESHOLD",
        parameters={"threshold": 1000.0},
        severity="LOW",
        enabled=True,
    )
    FraudRule.objects.create(
        name="Disabled Rule",
        rule_type="AMOUNT_THRESHOLD",
        parameters={"threshold": 2000.0},
        severity="LOW",
        enabled=False,
    )

    res_enabled = api_client.get("/api/admin/fraud-rules/?enabled=true")
    assert res_enabled.status_code == 200
    results = res_enabled.data.get("results", res_enabled.data)
    assert all(r["enabled"] is True for r in results)


def test_drf_fraud_rules_mutations_disallowed(api_client: APIClient) -> None:
    # ReadOnlyModelViewSet must reject POST, PUT, PATCH, DELETE with 405 Method Not Allowed
    res_post = api_client.post("/api/admin/fraud-rules/", {"name": "Disallowed"})
    assert res_post.status_code == 405

    rule = FraudRule.objects.create(
        name="Immutable Via API",
        rule_type="AMOUNT_THRESHOLD",
        parameters={"threshold": 1000.0},
        severity="LOW",
        enabled=True,
    )
    res_put = api_client.put(f"/api/admin/fraud-rules/{rule.id}/", {"name": "Mutated"})
    assert res_put.status_code == 405

    res_delete = api_client.delete(f"/api/admin/fraud-rules/{rule.id}/")
    assert res_delete.status_code == 405


def test_drf_audit_logs_list_and_filter(api_client: APIClient) -> None:
    test_corr_id = uuid.uuid4()
    AuditLog.objects.create(
        actor="system_test",
        action="TEST_ACTION",
        entity_type="TestEntity",
        entity_id="123",
        before={"key": "old"},
        after={"key": "new"},
        correlation_id=test_corr_id,
    )

    res_list = api_client.get("/api/admin/audit-logs/?action=TEST_ACTION")
    assert res_list.status_code == 200
    results = res_list.data.get("results", res_list.data)
    assert len(results) >= 1
    assert results[0]["action"] == "TEST_ACTION"
    assert results[0]["actor"] == "system_test"


def test_drf_users_list_and_mutations_disallowed(api_client: APIClient) -> None:
    unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    user = User.objects.create(
        full_name="Jane Doe",
        email=unique_email,
        country="GB",
        is_seed_data=False,
    )

    res_list = api_client.get("/api/admin/users/?country=GB")
    assert res_list.status_code == 200
    results = res_list.data.get("results", res_list.data)
    assert any(u["email"] == unique_email for u in results)

    # Mutation disallowed
    res_post = api_client.post("/api/admin/users/", {"full_name": "Disallowed"})
    assert res_post.status_code == 405


def test_drf_surveillance_endpoints_accessible(api_client: APIClient) -> None:
    res_alerts = api_client.get("/api/admin/alerts/")
    assert res_alerts.status_code == 200

    res_txns = api_client.get("/api/admin/transactions/")
    assert res_txns.status_code == 200

    res_profiles = api_client.get("/api/admin/risk-profiles/")
    assert res_profiles.status_code == 200
