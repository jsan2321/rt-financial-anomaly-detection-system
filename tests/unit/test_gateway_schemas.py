"""
Unit tests for Gateway transaction schemas.
Validates payload constraints, positive amounts, ISO codes, and forbidden extra fields.
"""

from decimal import Decimal
import uuid
from pydantic import ValidationError
import pytest

from services.gateway.schemas.transactions import (
    TransactionAcceptedResponse,
    TransactionCreateRequest,
)
from shared.models.enums import TransactionStatus


class TestTransactionCreateRequest:
    def test_valid_payload_creation(self):
        req = TransactionCreateRequest(
            amount=Decimal("150.75"),
            currency="usd",
            country="us",
            merchant_category="5411",
            user_id=uuid.uuid4(),
            idempotency_key="key-123",
            metadata={"demo_scenario": "burst"},
        )
        assert req.amount == Decimal("150.75")
        assert req.currency == "USD"
        assert req.country == "US"
        assert req.merchant_category == "5411"
        assert req.idempotency_key == "key-123"
        assert req.metadata["demo_scenario"] == "burst"

    def test_zero_amount_raises_error(self):
        with pytest.raises(ValidationError) as exc:
            TransactionCreateRequest(
                amount=Decimal("0.00"),
                currency="USD",
                country="US",
                merchant_category="retail",
                user_id=uuid.uuid4(),
            )
        assert "greater than 0" in str(exc.value)

    def test_negative_amount_raises_error(self):
        with pytest.raises(ValidationError) as exc:
            TransactionCreateRequest(
                amount=Decimal("-50.00"),
                currency="USD",
                country="US",
                merchant_category="retail",
                user_id=uuid.uuid4(),
            )
        assert "greater than 0" in str(exc.value)

    def test_invalid_currency_code(self):
        with pytest.raises(ValidationError) as exc:
            TransactionCreateRequest(
                amount=Decimal("100.00"),
                currency="US",  # only 2 chars
                country="US",
                merchant_category="retail",
                user_id=uuid.uuid4(),
            )
        assert "currency" in str(exc.value)

    def test_invalid_country_code(self):
        with pytest.raises(ValidationError) as exc:
            TransactionCreateRequest(
                amount=Decimal("100.00"),
                currency="USD",
                country="USA",  # 3 chars
                merchant_category="retail",
                user_id=uuid.uuid4(),
            )
        assert "country" in str(exc.value)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError) as exc:
            TransactionCreateRequest(
                amount=Decimal("100.00"),
                currency="USD",
                country="US",
                merchant_category="retail",
                user_id=uuid.uuid4(),
                unknown_extra_field="malicious_or_unexpected",
            )
        assert "Extra inputs are not permitted" in str(exc.value)


class TestTransactionAcceptedResponse:
    def test_response_instantiation(self):
        txn_id = uuid.uuid4()
        resp = TransactionAcceptedResponse(
            transaction_id=txn_id,
            status=TransactionStatus.SUBMITTED,
            correlation_id="corr-1234",
            status_url=f"/api/v1/transactions/{txn_id}",
        )
        assert resp.transaction_id == txn_id
        assert resp.status == TransactionStatus.SUBMITTED
        assert resp.correlation_id == "corr-1234"
        assert resp.status_url == f"/api/v1/transactions/{txn_id}"
