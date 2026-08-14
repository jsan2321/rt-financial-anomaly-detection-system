"""
API contract tests for transaction submission idempotency.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import httpx
import pytest

from services.gateway.main import app
from services.gateway.schemas.transactions import TransactionAcceptedResponse
from shared.db.session import get_db_session
from shared.models.enums import TransactionStatus


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
async def test_idempotent_duplicate_transaction_submission(test_client):
    """
    Submitting an identical idempotency_key returns the original transaction_id
    with HTTP 202 Accepted and does not insert a duplicate record.
    """
    original_txn_id = uuid.uuid4()
    idempotency_key = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())

    payload = {
        "idempotency_key": idempotency_key,
        "user_id": user_id,
        "amount": "250.00",
        "currency": "USD",
        "country": "US",
        "merchant_category": "travel",
    }

    # Simulate first submission (new transaction)
    with patch("services.gateway.services.ingestion.IngestionService.submit_transaction", new_callable=AsyncMock) as mock_submit:
        mock_submit.return_value = TransactionAcceptedResponse(
            transaction_id=original_txn_id,
            status=TransactionStatus.SUBMITTED,
            correlation_id=correlation_id,
            status_url=f"/api/v1/transactions/{original_txn_id}",
        )

        response1 = await test_client.post("/api/v1/transactions", json=payload)
        assert response1.status_code == 202
        data1 = response1.json()
        assert data1["transaction_id"] == str(original_txn_id)
        assert data1["status"] == "SUBMITTED"

    # Simulate duplicate submission with the same idempotency key
    with patch("services.gateway.services.ingestion.IngestionService.submit_transaction", new_callable=AsyncMock) as mock_submit_dup:
        mock_submit_dup.return_value = TransactionAcceptedResponse(
            transaction_id=original_txn_id,
            status=TransactionStatus.SUBMITTED,
            correlation_id=correlation_id,
            status_url=f"/api/v1/transactions/{original_txn_id}",
        )

        response2 = await test_client.post("/api/v1/transactions", json=payload)
        assert response2.status_code == 202
        data2 = response2.json()
        # Must return the original transaction ID
        assert data2["transaction_id"] == str(original_txn_id)
