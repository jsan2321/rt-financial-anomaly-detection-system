"""
Unit tests for Processor TransactionConsumer (Redis Streams + Inbox Idempotency + XAUTOCLAIM).
"""

import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
import redis.asyncio as aioredis

from services.processor.config import ProcessorSettings
from services.processor.consumers.transaction_consumer import (
    TransactionConsumer,
    parse_event_envelope,
)
from services.processor.domain.schemas import DetectionResult
from shared.events.envelope import EventEnvelope
from shared.events.event_types import EVENT_TRANSACTION_CREATED
from shared.models import DeadLetterEvent, ProcessedEvent
from shared.models.enums import AlertSeverity


@pytest.fixture
def mock_pipeline():
    pipeline = MagicMock()
    pipeline.process_transaction_event = AsyncMock()
    return pipeline


@pytest.fixture
def consumer_settings():
    return ProcessorSettings(
        STREAM_TRANSACTIONS="stream:transactions",
        GROUP_TRANSACTIONS="processor-group",
        CONSUMER_NAME="test-worker",
        MAX_CONSUMER_DELIVERIES=5,
        AUTOCLAIM_INTERVAL_SECONDS=0.1,
    )


def test_parse_event_envelope():
    event_id = str(uuid.uuid4())
    raw_env = {
        "event_id": event_id,
        "event_type": "transaction.created",
        "event_version": "1.0",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "producer_service": "gateway",
        "payload": {"amount": "100.00"},
    }

    # Case 1: "event" json string
    envelope1 = parse_event_envelope({"event": json.dumps(raw_env)})
    assert envelope1.event_id == event_id

    # Case 2: "envelope" dict
    envelope2 = parse_event_envelope({"envelope": raw_env})
    assert envelope2.event_id == event_id

    # Case 3: direct fields
    envelope3 = parse_event_envelope(raw_env)
    assert envelope3.event_id == event_id


@pytest.mark.asyncio
async def test_consumer_setup_group_success(mock_pipeline, consumer_settings):
    consumer = TransactionConsumer(pipeline=mock_pipeline, settings=consumer_settings)
    mock_redis = AsyncMock()

    await consumer.setup_consumer_group(mock_redis)

    mock_redis.xgroup_create.assert_awaited_once_with(
        name="stream:transactions",
        groupname="processor-group",
        id="$",
        mkstream=True,
    )


@pytest.mark.asyncio
async def test_consumer_setup_group_ignores_busygroup(mock_pipeline, consumer_settings):
    consumer = TransactionConsumer(pipeline=mock_pipeline, settings=consumer_settings)
    mock_redis = AsyncMock()
    mock_redis.xgroup_create.side_effect = aioredis.ResponseError("BUSYGROUP Consumer Group name already exists")

    # Should not raise exception
    await consumer.setup_consumer_group(mock_redis)


@pytest.mark.asyncio
async def test_consumer_process_single_message_new_event_commits_then_xacks(
    mock_pipeline, consumer_settings
):
    consumer = TransactionConsumer(pipeline=mock_pipeline, settings=consumer_settings)

    event_id = uuid.uuid4()
    envelope = EventEnvelope(
        event_id=str(event_id),
        correlation_id=str(uuid.uuid4()),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={"transaction_id": str(uuid.uuid4())},
    )

    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    # ProcessedEvent lookup returns None (new event)
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res

    mock_redis = AsyncMock()

    success = await consumer.process_single_message(
        db_manager=mock_db_manager,
        redis_client=mock_redis,
        stream_key="stream:transactions",
        message_id="1001-0",
        fields={"event": envelope.to_json()},
        delivery_count=1,
    )

    assert success is True
    # Pipeline was called
    mock_pipeline.process_transaction_event.assert_awaited_once_with(
        session=mock_session,
        event_envelope=envelope,
    )
    # XACK was called
    mock_redis.xack.assert_awaited_once_with(
        "stream:transactions",
        "processor-group",
        "1001-0",
    )


@pytest.mark.asyncio
async def test_consumer_process_single_message_duplicate_inbox_skips_and_xacks(
    mock_pipeline, consumer_settings
):
    consumer = TransactionConsumer(pipeline=mock_pipeline, settings=consumer_settings)

    event_id = uuid.uuid4()
    envelope = EventEnvelope(
        event_id=str(event_id),
        correlation_id=str(uuid.uuid4()),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={"transaction_id": str(uuid.uuid4())},
    )

    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    # ProcessedEvent lookup returns existing row (duplicate!)
    existing_processed = ProcessedEvent(
        event_id=event_id,
        consumer_group="processor-group",
        processed_at=datetime.now(timezone.utc),
    )
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = existing_processed
    mock_session.execute.return_value = mock_res

    mock_redis = AsyncMock()

    success = await consumer.process_single_message(
        db_manager=mock_db_manager,
        redis_client=mock_redis,
        stream_key="stream:transactions",
        message_id="1002-0",
        fields={"event": envelope.to_json()},
        delivery_count=1,
    )

    assert success is True
    # Pipeline was NOT called for duplicate
    mock_pipeline.process_transaction_event.assert_not_called()
    # XACK was called to clear message from PEL
    mock_redis.xack.assert_awaited_once_with(
        "stream:transactions",
        "processor-group",
        "1002-0",
    )


@pytest.mark.asyncio
async def test_consumer_pipeline_error_does_not_xack(mock_pipeline, consumer_settings):
    consumer = TransactionConsumer(pipeline=mock_pipeline, settings=consumer_settings)

    event_id = uuid.uuid4()
    envelope = EventEnvelope(
        event_id=str(event_id),
        correlation_id=str(uuid.uuid4()),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={"transaction_id": str(uuid.uuid4())},
    )

    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    # Not processed
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res

    # Pipeline raises Exception (e.g. transient DB error)
    mock_pipeline.process_transaction_event.side_effect = RuntimeError("Database connection lost")

    mock_redis = AsyncMock()

    success = await consumer.process_single_message(
        db_manager=mock_db_manager,
        redis_client=mock_redis,
        stream_key="stream:transactions",
        message_id="1003-0",
        fields={"event": envelope.to_json()},
        delivery_count=1,
    )

    assert success is False
    # XACK must NOT be called
    mock_redis.xack.assert_not_called()


@pytest.mark.asyncio
async def test_consumer_exceeded_deliveries_dead_letters(mock_pipeline, consumer_settings):
    consumer = TransactionConsumer(pipeline=mock_pipeline, settings=consumer_settings)

    event_id = uuid.uuid4()
    envelope = EventEnvelope(
        event_id=str(event_id),
        correlation_id=str(uuid.uuid4()),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={"transaction_id": str(uuid.uuid4())},
    )

    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    mock_session.add = MagicMock()

    mock_redis = AsyncMock()

    success = await consumer.process_single_message(
        db_manager=mock_db_manager,
        redis_client=mock_redis,
        stream_key="stream:transactions",
        message_id="1004-0",
        fields={"event": envelope.to_json()},
        delivery_count=6,  # > MAX_CONSUMER_DELIVERIES (5)
    )

    assert success is True
    # Pipeline was not called
    mock_pipeline.process_transaction_event.assert_not_called()

    # DeadLetterEvent was added and committed
    added_objects = [call[0][0] for call in mock_session.add.call_args_list]
    dlq_events = [obj for obj in added_objects if isinstance(obj, DeadLetterEvent)]
    assert len(dlq_events) == 1
    assert dlq_events[0].original_event_id == event_id
    mock_session.commit.assert_awaited_once()

    # XACK was called to prevent loop
    mock_redis.xack.assert_awaited_once_with(
        "stream:transactions",
        "processor-group",
        "1004-0",
    )


@pytest.mark.asyncio
async def test_consumer_autoclaim_loop_reclaims_and_processes(mock_pipeline, consumer_settings):
    consumer = TransactionConsumer(pipeline=mock_pipeline, settings=consumer_settings)

    event_id = uuid.uuid4()
    envelope = EventEnvelope(
        event_id=str(event_id),
        correlation_id=str(uuid.uuid4()),
        event_type=EVENT_TRANSACTION_CREATED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        producer_service="gateway",
        payload={"transaction_id": str(uuid.uuid4())},
    )

    mock_redis = AsyncMock()
    # xautoclaim returns [next_id, [(msg_id, fields)], [deleted_ids]]
    mock_redis.xautoclaim.return_value = (
        "0-0",
        [("reclaimed-101", {"event": envelope.to_json()})],
        [],
    )

    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res

    shutdown_event = asyncio.Event()

    # Run autoclaim in task and cancel after short delay
    task = asyncio.create_task(
        consumer.run_autoclaim_loop(
            db_manager=mock_db_manager,
            redis_client=mock_redis,
            shutdown_event=shutdown_event,
        )
    )

    await asyncio.sleep(0.15)
    shutdown_event.set()
    await task

    # Verified xautoclaim was called
    mock_redis.xautoclaim.assert_awaited()
    # Pipeline was called for the reclaimed message
    mock_pipeline.process_transaction_event.assert_awaited()
    # XACK was called for reclaimed message
    mock_redis.xack.assert_awaited_with(
        "stream:transactions",
        "processor-group",
        "reclaimed-101",
    )
