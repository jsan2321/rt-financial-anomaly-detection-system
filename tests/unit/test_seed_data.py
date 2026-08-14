"""
Unit tests for RT-FADS data seeding generator and CLI tool.
"""

from decimal import Decimal
import sys
from pathlib import Path
import uuid

import pytest

# Ensure scripts directory is on sys.path
scripts_path = Path(__file__).resolve().parents[2] / "scripts"
if str(scripts_path) not in sys.path:
    sys.path.insert(0, str(scripts_path))

from seed_data import (
    generate_deterministic_demo_payloads,
    generate_historical_transactions,
    generate_risk_profiles,
    generate_synthetic_users,
    parse_args,
    run_seed,
)


def test_generate_synthetic_users() -> None:
    users = generate_synthetic_users(100)
    assert len(users) == 100

    emails = set()
    for u in users:
        assert isinstance(u["id"], uuid.UUID)
        assert len(u["full_name"]) > 0
        assert "@" in u["email"]
        assert len(u["country"]) == 2
        assert u["is_seed_data"] is True
        emails.add(u["email"])

    # Ensure unique emails
    assert len(emails) == 100


def test_generate_historical_transactions() -> None:
    users = generate_synthetic_users(10)
    txns = generate_historical_transactions(users, count=50, days_back=30)
    assert len(txns) == 50

    user_ids = {u["id"] for u in users}
    for t in txns:
        assert isinstance(t["id"], uuid.UUID)
        assert t["user_id"] in user_ids
        assert t["status"] == "PROCESSED"
        assert t["amount"] > Decimal("0.00")
        assert len(t["currency"]) == 3
        assert len(t["country"]) == 2
        assert t["created_at"] <= t["processed_at"]
        assert t["idempotency_key"].startswith("seed-hist-")


def test_generate_risk_profiles() -> None:
    users = generate_synthetic_users(20)
    txns = generate_historical_transactions(users, count=100)
    profiles = generate_risk_profiles(users, txns)

    assert len(profiles) == 20
    user_ids = {u["id"] for u in users}

    for p in profiles:
        assert p["user_id"] in user_ids
        assert Decimal("0.0") <= p["risk_score"] <= Decimal("1.0")
        assert p["total_alerts"] == 0
        assert p["false_positive_count"] == 0


def test_generate_deterministic_demo_payloads() -> None:
    users = generate_synthetic_users(5)
    payloads = generate_deterministic_demo_payloads(users)

    assert len(payloads) >= 2
    scenarios = [p["metadata"]["demo_scenario"] for p in payloads]
    assert "high_risk_jurisdiction" in scenarios
    assert "velocity_burst" in scenarios

    for p in payloads:
        assert Decimal(p["amount"]) > Decimal("0.00")
        assert len(p["currency"]) == 3
        assert len(p["country"]) == 2
        assert "user_id" in p
        assert p["idempotency_key"].startswith("seed-demo-")


def test_parse_args_defaults() -> None:
    opts = parse_args([])
    assert opts.users == 100
    assert opts.transactions == 1000
    assert opts.gateway_url == "http://localhost:8000"
    assert opts.force is False
    assert opts.dry_run is False


def test_parse_args_custom() -> None:
    opts = parse_args(["--users", "250", "--transactions", "5000", "--force", "--dry-run"])
    assert opts.users == 250
    assert opts.transactions == 5000
    assert opts.force is True
    assert opts.dry_run is True


@pytest.mark.asyncio
async def test_run_seed_dry_run() -> None:
    result = await run_seed(user_count=25, txn_count=75, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["users"] == 25
    assert result["transactions"] == 75
    assert result["risk_profiles"] == 25
    assert result["demo_payloads"] >= 2
