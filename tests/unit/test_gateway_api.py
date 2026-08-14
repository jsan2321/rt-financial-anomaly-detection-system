"""
Unit and API integration tests for Gateway endpoints.
Tests /healthz, /readyz, POST /api/v1/transactions, GET /api/v1/transactions/{id},
and error envelope validation.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import httpx
import pytest

from services.gateway.main import app
from shared.context.correlation import CORRELATION_ID_HEADER
from shared.db.session import get_db_session
from shared.models import Alert, Transaction
from shared.models.enums import AlertSeverity, AlertStatus, TransactionStatus


@pytest.fixture
def mock_db_session():
    mock_session = AsyncMock()
    return mock_session


@pytest.fixture
def test_client(mock_db_session):
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_healthz_endpoint(test_client):
    response = await test_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz_endpoint_healthy(test_client):
    with patch("services.gateway.api.health.ping_database", new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = True
        response = await test_client.get("/readyz")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "database": "connected"}


@pytest.mark.asyncio
async def test_readyz_endpoint_unhealthy(test_client):
    with patch("services.gateway.api.health.ping_database", new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = False
        response = await test_client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_post_transactions_success(test_client, mock_db_session):
    # No existing duplicate
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_result

    user_id = str(uuid.uuid4())
    payload = {
        "amount": "199.99",
        "currency": "USD",
        "country": "US",
        "merchant_category": "5411",
        "user_id": user_id,
        "idempotency_key": "idemp-001",
    }
    custom_corr_id = str(uuid.uuid4())

    response = await test_client.post(
        "/api/v1/transactions",
        json=payload,
        headers={CORRELATION_ID_HEADER: custom_corr_id},
    )

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "SUBMITTED"
    assert data["correlation_id"] == custom_corr_id
    assert "/api/v1/transactions/" in data["status_url"]
    assert response.headers.get(CORRELATION_ID_HEADER) == custom_corr_id


@pytest.mark.asyncio
async def test_post_transactions_validation_error_envelope(test_client):
    # Invalid amount <= 0
    payload = {
        "amount": "-50.00",
        "currency": "USD",
        "country": "US",
        "merchant_category": "5411",
        "user_id": str(uuid.uuid4()),
    }

    response = await test_client.post("/api/v1/transactions", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "correlation_id" in data["error"]
    assert "details" in data["error"]


@pytest.mark.asyncio
async def test_post_transactions_forbidden_extra_field(test_client):
    payload = {
        "amount": "100.00",
        "currency": "USD",
        "country": "US",
        "merchant_category": "5411",
        "user_id": str(uuid.uuid4()),
        "extra_disallowed_property": "attack",
    }

    response = await test_client.post("/api/v1/transactions", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_get_transaction_by_id_success(test_client, mock_db_session):
    txn_id = uuid.uuid4()
    user_id = uuid.uuid4()
    txn = Transaction(
        id=txn_id,
        user_id=user_id,
        amount=Decimal("350.00"),
        currency="USD",
        country="US",
        merchant_category="electronics",
        status=TransactionStatus.PROCESSED.value,
        idempotency_key="key-002",
        correlation_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )

    mock_txn_res = MagicMock()
    mock_txn_res.scalar_one_or_none.return_value = txn
    mock_alert_res = MagicMock()
    mock_alert_res.scalar_one_or_none.return_value = None
    mock_db_session.execute.side_effect = [mock_txn_res, mock_alert_res]

    response = await test_client.get(f"/api/v1/transactions/{txn_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["transaction_id"] == str(txn_id)
    assert data["status"] == "PROCESSED"
    assert data["amount"] == "350.00"
    assert data["alert"] is None


@pytest.mark.asyncio
async def test_get_transaction_by_id_not_found(test_client, mock_db_session):
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_res

    missing_id = uuid.uuid4()
    response = await test_client.get(f"/api/v1/transactions/{missing_id}")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert str(missing_id) in data["error"]["message"]
