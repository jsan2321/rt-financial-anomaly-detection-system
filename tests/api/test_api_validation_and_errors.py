"""
API contract tests for request validation, forbidden extra fields, and error envelopes.
"""

from unittest.mock import AsyncMock, MagicMock
import uuid

import httpx
import pytest

from services.gateway.main import app
from shared.db.session import get_db_session


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
async def test_validation_missing_required_fields(test_client):
    """Missing user_id, amount, or idempotency_key triggers 422 with standard error envelope."""
    payload = {
        "currency": "USD",
        "country": "US",
    }
    response = await test_client.post("/api/v1/transactions", json=payload)
    assert response.status_code == 422

    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "message" in body["error"]
    assert "details" in body["error"]
    assert "correlation_id" in body["error"]


@pytest.mark.asyncio
async def test_validation_forbidden_extra_properties(test_client):
    """Unrecognized / extra fields in request payload must be rejected with 422."""
    payload = {
        "idempotency_key": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "amount": "100.00",
        "currency": "USD",
        "country": "US",
        "merchant_category": "retail",
        "illegal_extra_field": "disallowed_value",
    }
    response = await test_client.post("/api/v1/transactions", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_validation_non_positive_amount(test_client):
    """Amounts <= 0.00 must be rejected."""
    payload = {
        "idempotency_key": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "amount": "0.00",
        "currency": "USD",
        "country": "US",
        "merchant_category": "retail",
    }
    response = await test_client.post("/api/v1/transactions", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"

    # Negative amount
    payload["amount"] = "-25.50"
    response_neg = await test_client.post("/api/v1/transactions", json=payload)
    assert response_neg.status_code == 422


@pytest.mark.asyncio
async def test_validation_invalid_currency(test_client):
    """Currencies not matching 3 uppercase letters must be rejected."""
    payload = {
        "idempotency_key": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "amount": "10.00",
        "currency": "usd_dollar",
        "country": "US",
        "merchant_category": "retail",
    }
    response = await test_client.post("/api/v1/transactions", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_alert_get_nonexistent_returns_404(test_client, mock_db_session):
    """Requesting an alert that does not exist returns 404 with error envelope."""
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_res

    random_id = uuid.uuid4()
    response = await test_client.get(f"/api/v1/alerts/{random_id}")
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "NOT_FOUND"
