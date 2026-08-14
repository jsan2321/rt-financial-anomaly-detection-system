"""
Unit tests for Processor worker configuration settings.
"""

from decimal import Decimal
import pytest

from services.processor.config import ProcessorSettings


def test_processor_settings_defaults():
    settings = ProcessorSettings()
    assert settings.APP_NAME == "rt-fads-processor"
    assert settings.STREAM_TRANSACTIONS == "stream:transactions"
    assert settings.GROUP_TRANSACTIONS == "processor-group"
    assert settings.CONSUMER_BATCH_SIZE == 10
    assert settings.CONSUMER_BLOCK_MS == 2000
    assert settings.AUTOCLAIM_INTERVAL_SECONDS == 30.0
    assert settings.AUTOCLAIM_MIN_IDLE_TIME_MS == 30000
    assert settings.MAX_CONSUMER_DELIVERIES == 5
    assert settings.FRAUD_RULE_REFRESH_SECONDS == 30.0
    assert settings.VELOCITY_WINDOW_MINUTES == 10
    assert settings.ALERT_THRESHOLD == Decimal("0.60")
    assert settings.W_RULE == Decimal("0.5")
    assert settings.W_ML == Decimal("0.3")
    assert settings.W_PROFILE == Decimal("0.2")
    assert settings.DEMO_MODE is False


def test_processor_settings_custom_overrides(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("ALERT_THRESHOLD", "0.75")
    monkeypatch.setenv("CONSUMER_BATCH_SIZE", "25")
    monkeypatch.setenv("FRAUD_RULE_REFRESH_SECONDS", "15.0")

    settings = ProcessorSettings()
    assert settings.DEMO_MODE is True
    assert settings.ALERT_THRESHOLD == Decimal("0.75")
    assert settings.CONSUMER_BATCH_SIZE == 25
    assert settings.FRAUD_RULE_REFRESH_SECONDS == 15.0
