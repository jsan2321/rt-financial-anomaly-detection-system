"""
Integration tests for the Outbox Publisher poll-publish-mark lifecycle and outage resilience.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from services.outbox_publisher.config import OutboxPublisherSettings
from services.outbox_publisher.publisher import OutboxPublisher
from shared.events.event_types import EVENT_TRANSACTION_CREATED, STREAM_TRANSACTIONS
from shared.models import OutboxEvent
from shared.models.enums import OutboxStatus


@pytest.mark.asyncio
async def test_outbox_poll_publish_mark_cycle_success():
    publisher = OutboxPublisher(settings=OutboxPublisherSettings(BATCH_SIZE=10))

    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0.0",
        payload={"transaction_id": str(uuid.uuid4()), "amount": "50.00"},
        correlation_id=uuid.uuid4(),
        producer_service="gateway",
        status=OutboxStatus.PENDING.value,
        retry_count=0,
        created_at=datetime.now(timezone.utc),
    )

    mock_session = AsyncMock()
    exec_mock = MagicMock()
    exec_mock.scalars.return_value.all.return_value = [event]
    mock_session.execute.return_value = exec_mock

    mock_redis = AsyncMock()
    mock_redis.xadd.return_value = "1000-0"

    count = await publisher.publish_batch(mock_session, mock_redis)

    assert count == 1
    assert event.status == OutboxStatus.PUBLISHED.value
    assert event.published_at is not None
    mock_redis.xadd.assert_awaited_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_outbox_temporary_redis_failure_increments_retry():
    publisher = OutboxPublisher(settings=OutboxPublisherSettings(MAX_RETRIES=5))

    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0.0",
        payload={"transaction_id": str(uuid.uuid4())},
        correlation_id=uuid.uuid4(),
        producer_service="gateway",
        status=OutboxStatus.PENDING.value,
        retry_count=0,
        created_at=datetime.now(timezone.utc),
    )

    mock_session = AsyncMock()
    exec_mock = MagicMock()
    exec_mock.scalars.return_value.all.return_value = [event]
    mock_session.execute.return_value = exec_mock

    mock_redis = AsyncMock()
    mock_redis.xadd.side_effect = ConnectionError("Redis connection lost")

    count = await publisher.publish_batch(mock_session, mock_redis)

    assert count == 1
    assert event.retry_count == 1
    assert event.status == OutboxStatus.PENDING.value
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_outbox_max_retries_exceeded_dead_letters():
    publisher = OutboxPublisher(settings=OutboxPublisherSettings(MAX_RETRIES=3))

    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0.0",
        payload={"transaction_id": str(uuid.uuid4())},
        correlation_id=uuid.uuid4(),
        producer_service="gateway",
        status=OutboxStatus.PENDING.value,
        retry_count=2,  # next failure reaches 3
        created_at=datetime.now(timezone.utc),
    )

    mock_session = AsyncMock()
    exec_mock = MagicMock()
    exec_mock.scalars.return_value.all.return_value = [event]
    mock_session.execute.return_value = exec_mock

    mock_redis = AsyncMock()
    mock_redis.xadd.side_effect = RuntimeError("Persistent broker failure")

    count = await publisher.publish_batch(mock_session, mock_redis)

    assert count == 1
    assert event.retry_count == 3
    assert event.status == OutboxStatus.DEAD_LETTERED.value
    mock_session.add.assert_called_once()
    dead_letter_arg = mock_session.add.call_args[0][0]
    assert dead_letter_arg.original_event_id == event.id
    assert dead_letter_arg.stream_name == STREAM_TRANSACTIONS
    mock_session.commit.assert_awaited_once()
