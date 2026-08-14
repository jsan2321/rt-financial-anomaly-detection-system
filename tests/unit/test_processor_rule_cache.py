"""
Unit tests for Processor in-memory RuleCache.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from services.processor.domain.schemas import RuleDefinition
from services.processor.services.rule_cache import RuleCache
from shared.models.enums import AlertSeverity, RuleType
from shared.models.fraud_rule import FraudRule


@pytest.mark.asyncio
async def test_rule_cache_initial_empty():
    cache = RuleCache(refresh_ttl_seconds=30.0)
    assert cache.cached_rule_count == 0
    assert cache.last_refreshed_at is None


@pytest.mark.asyncio
async def test_rule_cache_set_rules_for_testing():
    cache = RuleCache(refresh_ttl_seconds=30.0)
    rule1 = RuleDefinition(
        id=uuid.uuid4(),
        name="Rule 1",
        rule_type=RuleType.AMOUNT_THRESHOLD,
        parameters={"threshold": 1000},
        severity=AlertSeverity.HIGH,
        enabled=True,
    )
    cache.set_rules_for_testing([rule1])
    assert cache.cached_rule_count == 1
    assert cache.last_refreshed_at is not None


@pytest.mark.asyncio
async def test_rule_cache_get_active_rules_from_db():
    cache = RuleCache(refresh_ttl_seconds=30.0)

    db_rule_1 = FraudRule(
        id=uuid.uuid4(),
        name="High Amount",
        rule_type="AMOUNT_THRESHOLD",
        parameters={"threshold": 5000},
        severity="HIGH",
        enabled=True,
    )
    db_rule_2 = FraudRule(
        id=uuid.uuid4(),
        name="Sanctioned Country",
        rule_type="HIGH_RISK_COUNTRY",
        parameters={"countries": ["KP", "IR"]},
        severity="CRITICAL",
        enabled=True,
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [db_rule_1, db_rule_2]
    mock_session.execute.return_value = mock_result

    rules = await cache.get_active_rules(mock_session)
    assert len(rules) == 2
    assert rules[0].name == "High Amount"
    assert rules[0].severity == AlertSeverity.HIGH
    assert rules[1].name == "Sanctioned Country"
    assert rules[1].severity == AlertSeverity.CRITICAL
    assert mock_session.execute.call_count == 1

    # Second call within TTL should return cached copy without DB query
    cached_rules = await cache.get_active_rules(mock_session)
    assert len(cached_rules) == 2
    assert mock_session.execute.call_count == 1

    # Force refresh should trigger DB query again
    refreshed_rules = await cache.get_active_rules(mock_session, force_refresh=True)
    assert len(refreshed_rules) == 2
    assert mock_session.execute.call_count == 2


@pytest.mark.asyncio
async def test_rule_cache_skips_invalid_db_rule():
    cache = RuleCache(refresh_ttl_seconds=30.0)

    valid_rule = FraudRule(
        id=uuid.uuid4(),
        name="Valid Rule",
        rule_type="AMOUNT_THRESHOLD",
        parameters={"threshold": 100},
        severity="LOW",
        enabled=True,
    )
    invalid_rule = FraudRule(
        id=uuid.uuid4(),
        name="Invalid Rule",
        rule_type="UNKNOWN_TYPE_INVALID",
        parameters={},
        severity="INVALID_SEVERITY",
        enabled=True,
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [valid_rule, invalid_rule]
    mock_session.execute.return_value = mock_result

    rules = await cache.get_active_rules(mock_session)
    assert len(rules) == 1
    assert rules[0].name == "Valid Rule"
