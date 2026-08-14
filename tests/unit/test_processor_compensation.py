"""
Unit tests for Processor CompensationConsumer and RiskCompensationService.
Tests business-level risk profile recalculation, ProcessedEvent inbox idempotency,
dead-letter handling, and XAUTOCLAIM crash recovery.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from services.processor.config import ProcessorSettings
from services.processor.consumers.compensation_consumer import CompensationConsumer
from services.processor.services.compensation_service import RiskCompensationService
from shared.events.envelope import EventEnvelope
from shared.events.event_types import EVENT_RISK_PROFILE_RECALCULATE
from shared.models import DeadLetterEvent, ProcessedEvent, RiskProfile


@pytest.fixture
def compensation_service() -> RiskCompensationService:
    return RiskCompensationService()


@pytest.fixture
def processor_settings() -> ProcessorSettings:
    return ProcessorSettings(
        STREAM_COMPENSATION="stream:compensation",
        GROUP_COMPENSATION="processor-compensation-group",
        MAX_CONSUMER_DELIVERIES=5,
        AUTOCLAIM_INTERVAL_SECONDS=0.1,
    )


@pytest.fixture
def compensation_consumer(compensation_service, processor_settings) -> CompensationConsumer:
    return CompensationConsumer(
        compensation_service=compensation_service,
        settings=processor_settings,
    )


@pytest.mark.asyncio
async def test_compensation_service_recalculate_existing_profile(compensation_service):
    mock_session = AsyncMock()
    user_id = uuid.uuid4()

    existing_profile = RiskProfile(
        user_id=user_id,
        risk_score=Decimal("0.5000"),
        total_alerts=2,
        false_positive_count=0,
        last_recalculated_at=datetime.now(timezone.utc),
    )

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = existing_profile
    mock_session.execute.return_value = mock_res

    updated_profile = await compensation_service.recalculate_user_risk_profile(
        session=mock_session,
        user_id=user_id,
        alert_id=uuid.uuid4(),
    )

    assert updated_profile.false_positive_count == 1
    # 2 alerts - 1 false positive = 1 effective alert -> score = 0.2500
    assert updated_profile.risk_score == Decimal("0.2500")


@pytest.mark.asyncio
async def test_compensation_service_create_initial_profile(compensation_service):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    user_id = uuid.uuid4()

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res

    profile = await compensation_service.recalculate_user_risk_profile(
        session=mock_session,
        user_id=user_id,
    )

    assert profile.user_id == user_id
    assert profile.false_positive_count == 1
    assert profile.total_alerts == 0
    assert profile.risk_score == Decimal("0.0000")
    mock_session.add.assert_called_once_with(profile)


@pytest.mark.asyncio
async def test_compensation_consumer_process_success(compensation_consumer):
    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    # Inbox check returns None (not processed yet)
    mock_inbox_res = MagicMock()
    mock_inbox_res.scalar_one_or_none.return_value = None

    # RiskProfile query returns existing profile
    user_id = uuid.uuid4()
    profile = RiskProfile(
        user_id=user_id,
        risk_score=Decimal("0.7500"),
        total_alerts=3,
        false_positive_count=0,
    )
    mock_profile_res = MagicMock()
    mock_profile_res.scalar_one_or_none.return_value = profile

    mock_session.execute.side_effect = [mock_inbox_res, mock_profile_res]

    mock_redis = AsyncMock()

    event_id = uuid.uuid4()
    envelope = EventEnvelope(
        event_id=str(event_id),
        event_type=EVENT_RISK_PROFILE_RECALCULATE,
        producer_service="gateway",
        payload={"user_id": str(user_id), "alert_id": str(uuid.uuid4())},
    )

    fields = {"event": json.dumps(envelope.model_dump(mode="json"))}

    success = await compensation_consumer.process_single_message(
        db_manager=mock_db_manager,
        redis_client=mock_redis,
        stream_key="stream:compensation",
        message_id="100-0",
        fields=fields,
    )

    assert success is True

    # Check ProcessedEvent added
    added_objects = [call[0][0] for call in mock_session.add.call_args_list]
    inbox_events = [obj for obj in added_objects if isinstance(obj, ProcessedEvent)]
    assert len(inbox_events) == 1
    assert inbox_events[0].event_id == event_id
    assert inbox_events[0].consumer_group == "processor-compensation-group"

    # Check commit was awaited
    mock_session.commit.assert_awaited_once()

    # Check XACK was sent AFTER commit
    mock_redis.xack.assert_awaited_once_with(
        "stream:compensation",
        "processor-compensation-group",
        "100-0",
    )


@pytest.mark.asyncio
async def test_compensation_consumer_idempotency_duplicate_skipped(compensation_consumer):
    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    # Inbox check returns already processed row
    already_processed = ProcessedEvent(
        event_id=uuid.uuid4(),
        consumer_group="processor-compensation-group",
        processed_at=datetime.now(timezone.utc),
    )
    mock_inbox_res = MagicMock()
    mock_inbox_res.scalar_one_or_none.return_value = already_processed
    mock_session.execute.return_value = mock_inbox_res

    mock_redis = AsyncMock()

    envelope = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=EVENT_RISK_PROFILE_RECALCULATE,
        producer_service="gateway",
        payload={"user_id": str(uuid.uuid4())},
    )

    fields = {"event": json.dumps(envelope.model_dump(mode="json"))}

    with patch.object(
        compensation_consumer.compensation_service,
        "recalculate_user_risk_profile",
        new_callable=AsyncMock,
    ) as mock_recalculate:
        success = await compensation_consumer.process_single_message(
            db_manager=mock_db_manager,
            redis_client=mock_redis,
            stream_key="stream:compensation",
            message_id="101-0",
            fields=fields,
        )

        assert success is True
        # Recalculate must NOT be called for duplicate event (FR-COMP-004)
        mock_recalculate.assert_not_called()
        # But XACK must be sent to acknowledge the duplicate
        mock_redis.xack.assert_awaited_once_with(
            "stream:compensation",
            "processor-compensation-group",
            "101-0",
        )


@pytest.mark.asyncio
async def test_compensation_consumer_error_does_not_xack(compensation_consumer):
    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    mock_inbox_res = MagicMock()
    mock_inbox_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_inbox_res
    mock_session.commit.side_effect = Exception("Database connection failure")

    mock_redis = AsyncMock()

    envelope = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=EVENT_RISK_PROFILE_RECALCULATE,
        producer_service="gateway",
        payload={"user_id": str(uuid.uuid4())},
    )
    fields = {"event": json.dumps(envelope.model_dump(mode="json"))}

    success = await compensation_consumer.process_single_message(
        db_manager=mock_db_manager,
        redis_client=mock_redis,
        stream_key="stream:compensation",
        message_id="102-0",
        fields=fields,
    )

    assert success is False
    # XACK must NOT be sent on failure
    mock_redis.xack.assert_not_called()


@pytest.mark.asyncio
async def test_compensation_consumer_dead_letter_on_max_deliveries(compensation_consumer):
    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    mock_redis = AsyncMock()

    fields = {"raw": "corrupted payload"}

    success = await compensation_consumer.process_single_message(
        db_manager=mock_db_manager,
        redis_client=mock_redis,
        stream_key="stream:compensation",
        message_id="103-0",
        fields=fields,
        delivery_count=6,  # > 5
    )

    assert success is True

    # DeadLetterEvent recorded
    added_objects = [call[0][0] for call in mock_session.add.call_args_list]
    dead_letters = [obj for obj in added_objects if isinstance(obj, DeadLetterEvent)]
    assert len(dead_letters) == 1
    assert dead_letters[0].stream_name == "stream:compensation"
    assert dead_letters[0].consumer_group == "processor-compensation-group"

    # Acknowledged to remove from stream
    mock_redis.xack.assert_awaited_once_with(
        "stream:compensation",
        "processor-compensation-group",
        "103-0",
    )


@pytest.mark.asyncio
async def test_compensation_autoclaim_recovery(compensation_consumer):
    mock_db_manager = MagicMock()
    mock_redis = AsyncMock()

    envelope = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=EVENT_RISK_PROFILE_RECALCULATE,
        producer_service="gateway",
        payload={"user_id": str(uuid.uuid4())},
    )
    raw_fields = {"event": json.dumps(envelope.model_dump(mode="json"))}

    # xautoclaim returns recovered message
    mock_redis.xautoclaim.return_value = ("0-0", [("104-0", raw_fields)])

    shutdown_event = asyncio.Event()

    with patch.object(
        compensation_consumer,
        "process_single_message",
        new_callable=AsyncMock,
    ) as mock_process:
        mock_process.return_value = True

        task = asyncio.create_task(
            compensation_consumer.run_autoclaim_loop(
                db_manager=mock_db_manager,
                redis_client=mock_redis,
                shutdown_event=shutdown_event,
            )
        )

        await asyncio.sleep(0.15)
        shutdown_event.set()
        await task

        mock_process.assert_called()
