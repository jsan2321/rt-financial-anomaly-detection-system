"""
Unit and API integration tests for Gateway Alert endpoints.
Tests GET /api/v1/alerts, GET /api/v1/alerts/{id}, POST /api/v1/alerts/{id}/approve,
POST /api/v1/alerts/{id}/block, POST /api/v1/alerts/{id}/false-positive, and 409 Conflict handling.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid

import httpx
import pytest

from services.gateway.main import app
from shared.context.correlation import CORRELATION_ID_HEADER
from shared.db.session import get_db_session
from shared.models import Alert
from shared.models.enums import AlertSeverity, AlertStatus


@pytest.fixture
def mock_db_session():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    return mock_session


@pytest.fixture
def test_client(mock_db_session):
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_alerts_list_api(test_client, mock_db_session):
    # Total count query
    mock_count = MagicMock()
    mock_count.scalar_one.return_value = 1

    # Items query
    alert = Alert(
        id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=AlertStatus.PENDING.value,
        severity=AlertSeverity.HIGH.value,
        composite_risk_score=Decimal("0.8000"),
        is_demo=False,
        created_at=datetime.now(timezone.utc),
    )
    mock_items = MagicMock()
    mock_items.scalars.return_value.all.return_value = [alert]

    mock_db_session.execute.side_effect = [mock_count, mock_items]

    response = await test_client.get("/api/v1/alerts?status=PENDING&page=1&page_size=20")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["status"] == "PENDING"
    assert data["items"][0]["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_get_alert_detail_api(test_client, mock_db_session):
    alert_id = uuid.uuid4()
    alert = Alert(
        id=alert_id,
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=AlertStatus.PENDING.value,
        severity=AlertSeverity.CRITICAL.value,
        composite_risk_score=Decimal("0.9500"),
        ml_anomaly_score=Decimal("0.8500"),
        rule_matches=[{"rule_name": "High Velocity", "severity": "CRITICAL"}],
        risk_profile_snapshot={"risk_score": "0.1000"},
        is_demo=False,
        correlation_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = alert
    mock_db_session.execute.return_value = mock_res

    response = await test_client.get(f"/api/v1/alerts/{alert_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(alert_id)
    assert data["status"] == "PENDING"
    assert data["severity"] == "CRITICAL"
    assert len(data["rule_matches"]) == 1


@pytest.mark.asyncio
async def test_get_alert_detail_not_found(test_client, mock_db_session):
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_res

    missing_id = uuid.uuid4()
    response = await test_client.get(f"/api/v1/alerts/{missing_id}")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_approve_alert_api(test_client, mock_db_session):
    alert_id = uuid.uuid4()
    mock_row = MagicMock(
        id=alert_id,
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="APPROVED",
        severity="HIGH",
    )
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = mock_row
    mock_db_session.execute.return_value = mock_update_res

    response = await test_client.post(
        f"/api/v1/alerts/{alert_id}/approve",
        json={"resolution_reason": "Verified legitimate purchase"},
        headers={"X-Actor": "analyst_sarah"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["alert_id"] == str(alert_id)
    assert data["status"] == "APPROVED"
    assert data["resolved_by"] == "analyst_sarah"
    assert data["resolution_reason"] == "Verified legitimate purchase"


@pytest.mark.asyncio
async def test_block_alert_api(test_client, mock_db_session):
    alert_id = uuid.uuid4()
    mock_row = MagicMock(
        id=alert_id,
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="BLOCKED",
        severity="CRITICAL",
    )
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = mock_row
    mock_db_session.execute.return_value = mock_update_res

    response = await test_client.post(
        f"/api/v1/alerts/{alert_id}/block",
        json={"resolution_reason": "Confirmed card takeover"},
        headers={"X-Actor": "analyst_john"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["alert_id"] == str(alert_id)
    assert data["status"] == "BLOCKED"
    assert data["resolved_by"] == "analyst_john"


@pytest.mark.asyncio
async def test_false_positive_alert_api(test_client, mock_db_session):
    alert_id = uuid.uuid4()
    mock_row = MagicMock(
        id=alert_id,
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="FALSE_POSITIVE",
        severity="MEDIUM",
    )
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = mock_row
    mock_db_session.execute.return_value = mock_update_res

    response = await test_client.post(
        f"/api/v1/alerts/{alert_id}/false-positive",
        json={"resolution_reason": "Merchant category misclassified"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["alert_id"] == str(alert_id)
    assert data["status"] == "FALSE_POSITIVE"
    assert data["resolved_by"] == "analyst_system"


@pytest.mark.asyncio
async def test_resolve_alert_conflict_returns_409(test_client, mock_db_session):
    alert_id = uuid.uuid4()

    # 1. Update fails (0 rows affected)
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = None

    # 2. Existing check finds it already terminal
    existing = Alert(
        id=alert_id,
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="BLOCKED",
        severity="CRITICAL",
    )
    mock_check_res = MagicMock()
    mock_check_res.scalar_one_or_none.return_value = existing

    mock_db_session.execute.side_effect = [mock_update_res, mock_check_res]

    response = await test_client.post(
        f"/api/v1/alerts/{alert_id}/approve",
        json={"resolution_reason": "Late approval attempt"},
    )

    assert response.status_code == 409
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert "Cannot transition alert" in data["error"]["message"]
