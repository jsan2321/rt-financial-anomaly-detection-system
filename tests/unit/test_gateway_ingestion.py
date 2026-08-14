"""
Unit tests for Gateway IngestionService.
Tests atomic transaction + outbox persistence, idempotency deduplication, and querying.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid
import pytest

from services.gateway.schemas.transactions import TransactionCreateRequest
from services.gateway.services.ingestion import IngestionService
from shared.errors.exceptions import ResourceNotFoundError
from shared.events.event_types import EVENT_TRANSACTION_CREATED
from shared.models import Alert, OutboxEvent, Transaction
from shared.models.enums import AlertSeverity, AlertStatus, TransactionStatus


@pytest.fixture
def ingestion_service() -> IngestionService:
    return IngestionService()


@pytest.fixture
def sample_payload() -> TransactionCreateRequest:
    return TransactionCreateRequest(
        amount=Decimal("250.00"),
        currency="USD",
        country="US",
        merchant_category="retail",
        user_id=uuid.uuid4(),
        idempotency_key="idemp-xyz-123",
        metadata={"demo_scenario": "velocity"},
    )


@pytest.mark.asyncio
async def test_submit_transaction_new_record_success(ingestion_service, sample_payload):
    mock_session = AsyncMock()

    # Existing check returns None (new transaction)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    correlation_id = str(uuid.uuid4())
    resp = await ingestion_service.submit_transaction(
        session=mock_session,
        payload=sample_payload,
        correlation_id=correlation_id,
    )

    assert resp.status == TransactionStatus.SUBMITTED
    assert resp.correlation_id == correlation_id
    assert str(resp.transaction_id) in resp.status_url

    # Verify session additions (Transaction and OutboxEvent)
    assert mock_session.add.call_count == 2
    added_objects = [call[0][0] for call in mock_session.add.call_args_list]

    txn_obj = next(obj for obj in added_objects if isinstance(obj, Transaction))
    outbox_obj = next(obj for obj in added_objects if isinstance(obj, OutboxEvent))

    assert txn_obj.amount == Decimal("250.00")
    assert txn_obj.idempotency_key == "idemp-xyz-123"
    assert txn_obj.status == TransactionStatus.SUBMITTED.value

    assert outbox_obj.event_type == EVENT_TRANSACTION_CREATED
    assert outbox_obj.producer_service == "gateway"
    assert outbox_obj.payload["transaction_id"] == str(txn_obj.id)
    assert outbox_obj.payload["amount"] == "250.00"

    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_transaction_idempotent_duplicate(ingestion_service, sample_payload):
    mock_session = AsyncMock()

    # Existing transaction already in DB
    existing_txn_id = uuid.uuid4()
    existing_corr_id = uuid.uuid4()
    existing_txn = Transaction(
        id=existing_txn_id,
        user_id=sample_payload.user_id,
        amount=sample_payload.amount,
        currency="USD",
        country="US",
        merchant_category="retail",
        status=TransactionStatus.SUBMITTED.value,
        idempotency_key="idemp-xyz-123",
        correlation_id=existing_corr_id,
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_txn
    mock_session.execute.return_value = mock_result

    resp = await ingestion_service.submit_transaction(
        session=mock_session,
        payload=sample_payload,
        correlation_id=str(uuid.uuid4()),
    )

    # Returns original transaction details without inserting new rows or committing
    assert resp.transaction_id == existing_txn_id
    assert resp.status == TransactionStatus.SUBMITTED
    assert resp.status_url == f"/api/v1/transactions/{existing_txn_id}"
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_transaction_with_alert(ingestion_service):
    mock_session = AsyncMock()

    txn_id = uuid.uuid4()
    txn = Transaction(
        id=txn_id,
        user_id=uuid.uuid4(),
        amount=Decimal("5000.00"),
        currency="USD",
        country="US",
        merchant_category="crypto",
        status=TransactionStatus.PROCESSED.value,
        idempotency_key="key-abc",
        correlation_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )

    alert_id = uuid.uuid4()
    alert = Alert(
        id=alert_id,
        transaction_id=txn_id,
        user_id=txn.user_id,
        status=AlertStatus.PENDING.value,
        severity=AlertSeverity.HIGH.value,
        composite_risk_score=Decimal("0.8500"),
        ml_anomaly_score=Decimal("0.7000"),
        correlation_id=txn.correlation_id,
    )

    # First execute call -> txn, Second execute call -> alert
    mock_txn_result = MagicMock()
    mock_txn_result.scalar_one_or_none.return_value = txn
    mock_alert_result = MagicMock()
    mock_alert_result.scalar_one_or_none.return_value = alert

    mock_session.execute.side_effect = [mock_txn_result, mock_alert_result]

    detail = await ingestion_service.get_transaction(mock_session, txn_id)
    assert detail.transaction_id == txn_id
    assert detail.status == TransactionStatus.PROCESSED
    assert detail.alert is not None
    assert detail.alert.id == alert_id
    assert detail.alert.status == "PENDING"
    assert detail.alert.severity == "HIGH"


@pytest.mark.asyncio
async def test_get_transaction_not_found_raises_error(ingestion_service):
    mock_session = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    non_existent_id = uuid.uuid4()
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await ingestion_service.get_transaction(mock_session, non_existent_id)
    assert "Transaction with ID" in exc_info.value.message
