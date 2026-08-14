"""
Integration tests for Redis Streams consumer group processing and inbox idempotency.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from services.processor.config import ProcessorSettings
from services.processor.consumers.transaction_consumer import TransactionConsumer
from shared.events.envelope import EventEnvelope
from shared.events.event_types import EVENT_TRANSACTION_CREATED
from shared.models import ProcessedEvent


@pytest.fixture
def mock_pipeline():
    pipeline = MagicMock()
    pipeline.process_transaction_event = AsyncMock()
    return pipeline


@pytest.mark.asyncio
async def test_consumer_group_lifecycle_and_message_ack(mock_pipeline):
    mock_redis = AsyncMock()
    custom_settings = ProcessorSettings(
        STREAM_TRANSACTIONS="stream:transactions",
        GROUP_TRANSACTIONS="test-processor-group",
        CONSUMER_NAME_TRANSACTIONS="worker-1",
    )
    consumer = TransactionConsumer(
        pipeline=mock_pipeline,
        settings=custom_settings,
    )

    # 1. Setup consumer group
    await consumer.setup_consumer_group(mock_redis)
    mock_redis.xgroup_create.assert_awaited_once_with(
        name="stream:transactions",
        groupname="test-processor-group",
        id="$",
        mkstream=True,
    )

    # 2. Process single new message
    event_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    envelope = EventEnvelope(
        event_id=event_id,
        correlation_id=correlation_id,
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0.0",
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={
            "transaction_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "amount": "150.00",
            "currency": "USD",
            "country": "US",
            "merchant_category": "electronics",
        },
    )

    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = exec_mock

    success = await consumer.process_single_message(
        db_manager=mock_db_manager,
        redis_client=mock_redis,
        stream_key="stream:transactions",
        message_id="1000-0",
        fields={"event": envelope.to_json()},
        delivery_count=1,
    )

    assert success is True
    # Verify pipeline was called and message acknowledged
    mock_pipeline.process_transaction_event.assert_awaited_once()
    mock_redis.xack.assert_awaited_once_with(
        "stream:transactions",
        "test-processor-group",
        "1000-0",
    )


@pytest.mark.asyncio
async def test_consumer_inbox_idempotency_skips_processing(mock_pipeline):
    mock_redis = AsyncMock()
    custom_settings = ProcessorSettings(
        STREAM_TRANSACTIONS="stream:transactions",
        GROUP_TRANSACTIONS="test-processor-group",
        CONSUMER_NAME_TRANSACTIONS="worker-1",
    )
    consumer = TransactionConsumer(
        pipeline=mock_pipeline,
        settings=custom_settings,
    )

    event_id = str(uuid.uuid4())
    envelope = EventEnvelope(
        event_id=event_id,
        correlation_id=str(uuid.uuid4()),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0.0",
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={"transaction_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4())},
    )

    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    existing_record = ProcessedEvent(
        event_id=uuid.UUID(event_id),
        consumer_group="test-processor-group",
        processed_at=datetime.now(timezone.utc),
    )
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.return_value = existing_record
    mock_session.execute.return_value = exec_mock

    success = await consumer.process_single_message(
        db_manager=mock_db_manager,
        redis_client=mock_redis,
        stream_key="stream:transactions",
        message_id="2000-0",
        fields={"event": envelope.to_json()},
        delivery_count=1,
    )

    assert success is True
    # Pipeline should NOT be invoked for duplicate event
    mock_pipeline.process_transaction_event.assert_not_awaited()
    # Message should still be acknowledged
    mock_redis.xack.assert_awaited_once_with(
        "stream:transactions",
        "test-processor-group",
        "2000-0",
    )
