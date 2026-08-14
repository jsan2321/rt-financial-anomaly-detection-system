"""
Unit tests for Outbox Publisher configuration.
"""

from services.outbox_publisher.config import OutboxPublisherSettings


def test_outbox_publisher_settings_defaults():
    settings = OutboxPublisherSettings()
    assert settings.APP_NAME == "rt-fads-outbox-publisher"
    assert settings.BATCH_SIZE == 50
    assert settings.MAX_RETRIES == 8
    assert settings.POLL_INTERVAL_SECONDS == 0.5
    assert settings.BACKOFF_BASE_SECONDS == 1.0


def test_outbox_publisher_custom_overrides():
    settings = OutboxPublisherSettings(
        BATCH_SIZE=100,
        MAX_RETRIES=5,
        POLL_INTERVAL_SECONDS=0.1,
    )
    assert settings.BATCH_SIZE == 100
    assert settings.MAX_RETRIES == 5
    assert settings.POLL_INTERVAL_SECONDS == 0.1
