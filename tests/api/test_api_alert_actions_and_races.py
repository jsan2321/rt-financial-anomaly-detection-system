"""
API contract tests for alert lifecycle action endpoints and conflict handling.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import uuid

import httpx
import pytest

from services.gateway.main import app
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
async def test_alert_action_approve_success(test_client, mock_db_session):
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
        json={"resolution_reason": "Verified legitimate customer purchase"},
        headers={"X-Actor": "analyst_sarah"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["alert_id"] == str(alert_id)
    assert data["status"] == "APPROVED"
    assert data["resolved_by"] == "analyst_sarah"
    assert data["resolution_reason"] == "Verified legitimate customer purchase"


@pytest.mark.asyncio
async def test_alert_action_block_success(test_client, mock_db_session):
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
async def test_alert_action_false_positive_success(test_client, mock_db_session):
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


@pytest.mark.asyncio
async def test_alert_action_conflict_when_already_resolved(test_client, mock_db_session):
    """Attempting to resolve an alert that has already been acted upon returns HTTP 409 Conflict."""
    alert_id = uuid.uuid4()

    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = None

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
