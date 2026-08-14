"""
Unit tests for OutboxPublisher worker.
Tests stream routing, batch publishing, Redis XADD serialization, retry handling, and dead-letter queue escalation.
"""

from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock
import uuid
import pytest

from services.outbox_publisher.config import OutboxPublisherSettings
from services.outbox_publisher.publisher import (
    OutboxPublisher,
    get_stream_for_event_type,
)
from shared.events.event_types import (
    EVENT_ALERT_CREATED,
    EVENT_ESCALATION_EMAIL_REQUESTED,
    EVENT_RISK_PROFILE_RECALCULATE,
    EVENT_TRANSACTION_CREATED,
    STREAM_ALERTS,
    STREAM_COMPENSATION,
    STREAM_ESCALATIONS,
    STREAM_TRANSACTIONS,
)
from shared.models import DeadLetterEvent, OutboxEvent
from shared.models.enums import OutboxStatus


@pytest.fixture
def publisher_settings() -> OutboxPublisherSettings:
    return OutboxPublisherSettings(
        BATCH_SIZE=10,
        MAX_RETRIES=3,
        POLL_INTERVAL_SECONDS=0.01,
    )


@pytest.fixture
def publisher(publisher_settings) -> OutboxPublisher:
    return OutboxPublisher(settings=publisher_settings)


@pytest.fixture
def sample_outbox_event() -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0",
        payload={"transaction_id": str(uuid.uuid4()), "amount": "150.00"},
        correlation_id=uuid.uuid4(),
        producer_service="gateway",
        status=OutboxStatus.PENDING.value,
        retry_count=0,
        created_at=datetime.now(timezone.utc),
    )


class TestStreamRouting:
    def test_get_stream_for_all_event_types(self):
        assert get_stream_for_event_type(EVENT_TRANSACTION_CREATED) == STREAM_TRANSACTIONS
        assert get_stream_for_event_type(EVENT_ALERT_CREATED) == STREAM_ALERTS
        assert get_stream_for_event_type("alert.approved") == STREAM_ALERTS
        assert get_stream_for_event_type("alert.blocked") == STREAM_ALERTS
        assert get_stream_for_event_type("alert.false_positive") == STREAM_ALERTS
        assert get_stream_for_event_type(EVENT_ESCALATION_EMAIL_REQUESTED) == STREAM_ESCALATIONS
        assert get_stream_for_event_type("escalation.slack.requested") == STREAM_ESCALATIONS
        assert get_stream_for_event_type(EVENT_RISK_PROFILE_RECALCULATE) == STREAM_COMPENSATION
        assert get_stream_for_event_type("custom.event") == "stream:custom"


class TestOutboxPublisherLogic:
    @pytest.mark.asyncio
    async def test_publish_event_xadd(self, publisher, sample_outbox_event):
        mock_redis = AsyncMock()
        mock_redis.xadd.return_value = "1723500000000-0"

        msg_id = await publisher.publish_event(mock_redis, sample_outbox_event)
        assert msg_id == "1723500000000-0"

        mock_redis.xadd.assert_awaited_once()
        call_kwargs = mock_redis.xadd.call_args.kwargs
        assert call_kwargs["name"] == STREAM_TRANSACTIONS
        assert "event" in call_kwargs["fields"]
        assert call_kwargs["fields"]["event_id"] == str(sample_outbox_event.id)
        assert call_kwargs["fields"]["event_type"] == EVENT_TRANSACTION_CREATED

        # Validate serialized envelope
        env_dict = json.loads(call_kwargs["fields"]["event"])
        assert env_dict["event_id"] == str(sample_outbox_event.id)
        assert env_dict["producer_service"] == "gateway"
        assert env_dict["payload"]["amount"] == "150.00"

    @pytest.mark.asyncio
    async def test_publish_batch_success(self, publisher, sample_outbox_event):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_outbox_event]
        mock_session.execute.return_value = mock_result

        mock_redis = AsyncMock()
        mock_redis.xadd.return_value = "1723500000000-0"

        count = await publisher.publish_batch(mock_session, mock_redis)
        assert count == 1
        assert sample_outbox_event.status == OutboxStatus.PUBLISHED.value
        assert sample_outbox_event.published_at is not None
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_batch_empty_returns_zero(self, publisher):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        mock_redis = AsyncMock()
        count = await publisher.publish_batch(mock_session, mock_redis)
        assert count == 0
        mock_redis.xadd.assert_not_awaited()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publish_failure_increments_retry(self, publisher, sample_outbox_event):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_outbox_event]
        mock_session.execute.return_value = mock_result

        mock_redis = AsyncMock()
        mock_redis.xadd.side_effect = ConnectionError("Redis connection lost")

        count = await publisher.publish_batch(mock_session, mock_redis)
        assert count == 1
        # Remains PENDING, retry_count incremented to 1
        assert sample_outbox_event.status == OutboxStatus.PENDING.value
        assert sample_outbox_event.retry_count == 1
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_dead_letters_event(self, publisher, sample_outbox_event):
        sample_outbox_event.retry_count = 2  # next failure reaches MAX_RETRIES (3)
        mock_session = AsyncMock()

        publisher.handle_publish_failure(
            session=mock_session,
            event=sample_outbox_event,
            error=ConnectionError("Persistent broker outage"),
        )

        assert sample_outbox_event.retry_count == 3
        assert sample_outbox_event.status == OutboxStatus.DEAD_LETTERED.value

        # Assert DeadLetterEvent was added to session
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert isinstance(added_obj, DeadLetterEvent)
        assert added_obj.original_event_id == sample_outbox_event.id
        assert added_obj.retry_count == 3
        assert added_obj.stream_name == STREAM_TRANSACTIONS
        assert "Persistent broker outage" in added_obj.error_message

    @pytest.mark.asyncio
    async def test_run_loop_graceful_shutdown(self, publisher):
        mock_db_manager = MagicMock()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        # Context manager for session_factory
        mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

        mock_redis = AsyncMock()
        import asyncio
        shutdown_event = asyncio.Event()

        # Set shutdown after starting
        async def trigger_shutdown():
            await asyncio.sleep(0.02)
            shutdown_event.set()

        asyncio.create_task(trigger_shutdown())
        await publisher.run_loop(mock_db_manager, mock_redis, shutdown_event)
        assert shutdown_event.is_set()
