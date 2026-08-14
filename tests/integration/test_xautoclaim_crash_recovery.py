"""
Integration tests for XAUTOCLAIM crash recovery and at-least-once delivery handling.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from services.processor.config import ProcessorSettings
from services.processor.consumers.transaction_consumer import TransactionConsumer
from shared.events.envelope import EventEnvelope
from shared.events.event_types import EVENT_TRANSACTION_CREATED
from shared.models import ProcessedEvent


@pytest.mark.asyncio
async def test_xautoclaim_recovers_pending_message_after_consumer_crash():
    """
    Scenario: Worker A crashes after message delivery.
    Worker B runs autoclaim, claims unacknowledged message, checks inbox, and acknowledges.
    """
    mock_pipeline = MagicMock()
    mock_pipeline.process_transaction_event = AsyncMock()

    mock_redis = AsyncMock()
    mock_db = MagicMock()

    custom_settings = ProcessorSettings(
        STREAM_TRANSACTIONS="stream:transactions",
        GROUP_TRANSACTIONS="processor-group",
        CONSUMER_NAME="worker-b-recovery",
        AUTOCLAIM_MIN_IDLE_TIME_MS=100,
        AUTOCLAIM_INTERVAL_SECONDS=0.05,
    )

    consumer_b = TransactionConsumer(
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
        payload={
            "transaction_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "amount": "999.00",
            "currency": "USD",
        },
    )

    # 1. Simulate XAUTOCLAIM returning an unacknowledged message originally assigned to dead worker-a
    reclaimed_msg_id = "1700000000000-0"
    mock_redis.xautoclaim.return_value = (
        "0-0",
        [(reclaimed_msg_id, {"event": envelope.to_json()})],
        [],
    )

    # 2. Simulate DB session factory
    mock_session = AsyncMock()
    existing_processed_record = ProcessedEvent(
        event_id=uuid.UUID(event_id),
        consumer_group="processor-group",
        processed_at=datetime.now(timezone.utc),
    )
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.return_value = existing_processed_record
    mock_session.execute.return_value = exec_mock

    mock_db.session_factory.return_value.__aenter__.return_value = mock_session

    shutdown_event = asyncio.Event()

    # 3. Execute autoclaim loop briefly
    task = asyncio.create_task(
        consumer_b.run_autoclaim_loop(
            db_manager=mock_db,
            redis_client=mock_redis,
            shutdown_event=shutdown_event,
        )
    )

    await asyncio.sleep(0.12)
    shutdown_event.set()
    await task

    # Assert xautoclaim was executed
    mock_redis.xautoclaim.assert_awaited()

    # Because ProcessedEvent was present, pipeline logic was NOT rerun
    mock_pipeline.process_transaction_event.assert_not_awaited()

    # The recovered message was successfully acknowledged
    mock_redis.xack.assert_awaited_with(
        "stream:transactions",
        "processor-group",
        reclaimed_msg_id,
    )
