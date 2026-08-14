"""
Unit tests for RT-FADS live transaction simulator.
"""

from decimal import Decimal
from pathlib import Path
import sys
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

# Ensure scripts directory is on sys.path
scripts_path = Path(__file__).resolve().parents[2] / "scripts"
if str(scripts_path) not in sys.path:
    sys.path.insert(0, str(scripts_path))

from simulate_live import (
    COMMON_COUNTRIES,
    HIGH_RISK_COUNTRIES,
    STANDARD_MERCHANT_CATEGORIES,
    SUSPICIOUS_MERCHANT_CATEGORIES,
    SimulationStats,
    currency_for_country,
    generate_fallback_users,
    generate_transaction_payload,
    parse_args,
    resolve_user_pool,
    run_simulator,
    submit_transaction_http,
)


def test_parse_args_defaults() -> None:
    opts = parse_args([])
    assert opts.gateway_url == "http://localhost:8000"
    assert opts.interval_min == 3.0
    assert opts.interval_max == 5.0
    assert opts.db_url is None
    assert opts.count is None
    assert opts.anomalous_ratio == 0.10
    assert opts.dry_run is False


def test_parse_args_custom() -> None:
    opts = parse_args([
        "--gateway-url", "http://custom-gw:9000",
        "--interval-min", "1.5",
        "--interval-max", "2.5",
        "--count", "100",
        "--anomalous-ratio", "0.25",
        "--dry-run",
    ])
    assert opts.gateway_url == "http://custom-gw:9000"
    assert opts.interval_min == 1.5
    assert opts.interval_max == 2.5
    assert opts.count == 100
    assert opts.anomalous_ratio == 0.25
    assert opts.dry_run is True


def test_currency_for_country() -> None:
    assert currency_for_country("US") == "USD"
    assert currency_for_country("DE") == "EUR"
    assert currency_for_country("FR") == "EUR"
    assert currency_for_country("GB") == "GBP"
    assert currency_for_country("CA") == "CAD"
    assert currency_for_country("JP") == "JPY"
    assert currency_for_country("AU") == "AUD"
    assert currency_for_country("XX") == "USD"


def test_generate_fallback_users() -> None:
    users = generate_fallback_users(25)
    assert len(users) == 25
    for u in users:
        assert isinstance(u["id"], uuid.UUID)
        assert u["country"] in COMMON_COUNTRIES


def test_generate_normal_transaction_payload() -> None:
    users = [{"id": uuid.uuid4(), "country": "US"}]
    payload, is_anom = generate_transaction_payload(users, anomalous_ratio=0.0)

    assert is_anom is False
    assert Decimal(payload["amount"]) > Decimal("0.00")
    assert Decimal(payload["amount"]) <= Decimal("500.00")
    assert len(payload["currency"]) == 3
    assert len(payload["country"]) == 2
    assert payload["merchant_category"] in STANDARD_MERCHANT_CATEGORIES
    assert payload["user_id"] == str(users[0]["id"])
    assert payload["idempotency_key"].startswith("sim-live-")
    assert payload["metadata"]["simulator"] is True
    assert payload["metadata"]["pattern"] == "normal"


def test_generate_anomalous_transaction_payload() -> None:
    users = [{"id": uuid.uuid4(), "country": "US"}]
    payload, is_anom = generate_transaction_payload(users, anomalous_ratio=1.0)

    assert is_anom is True
    assert Decimal(payload["amount"]) > Decimal("0.00")
    assert len(payload["currency"]) == 3
    assert len(payload["country"]) == 2
    assert payload["idempotency_key"].startswith("sim-live-")
    assert payload["metadata"]["simulator"] is True
    assert payload["metadata"]["pattern"] in ["high_amount", "high_risk_country", "high_risk_merchant", "combined"]


def test_simulation_stats() -> None:
    stats = SimulationStats()
    stats.record_submission(success=True, latency_ms=45.2, is_anomalous=False)
    stats.record_submission(success=True, latency_ms=55.8, is_anomalous=True)
    stats.record_submission(success=False, latency_ms=12.0, is_anomalous=False)

    assert stats.total_submitted == 3
    assert stats.total_accepted == 2
    assert stats.total_failed == 1
    assert stats.anomalous_count == 1
    assert len(stats.latencies) == 2


@pytest.mark.asyncio
async def test_resolve_user_pool_fallback() -> None:
    users = await resolve_user_pool(db_url="postgresql+asyncpg://invalid:5432/none", fallback_count=10)
    assert len(users) == 10
    assert isinstance(users[0]["id"], uuid.UUID)


@pytest.mark.asyncio
async def test_submit_transaction_http_success() -> None:
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.json.return_value = {"transaction_id": str(uuid.uuid4()), "status": "SUBMITTED"}
    mock_client.post.return_value = mock_response

    payload = {"amount": "100.00", "currency": "USD", "country": "US", "merchant_category": "groceries"}
    success, code, latency, txn_id = await submit_transaction_http(mock_client, "http://localhost:8000", payload)

    assert success is True
    assert code == 202
    assert latency >= 0.0
    assert txn_id is not None


@pytest.mark.asyncio
async def test_submit_transaction_http_failure() -> None:
    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("Connection refused")

    payload = {"amount": "100.00", "currency": "USD", "country": "US", "merchant_category": "groceries"}
    success, code, latency, err = await submit_transaction_http(mock_client, "http://localhost:8000", payload)

    assert success is False
    assert code == 0
    assert "Connection refused" in str(err)


@pytest.mark.asyncio
async def test_run_simulator_dry_run() -> None:
    users = [{"id": uuid.uuid4(), "country": "US"}]
    stats = await run_simulator(
        gateway_url="http://localhost:8000",
        interval_min=0.01,
        interval_max=0.02,
        count=5,
        anomalous_ratio=0.4,
        dry_run=True,
        users_pool_override=users,
    )

    assert stats.total_submitted == 5
    assert stats.total_accepted == 5
    assert stats.total_failed == 0
