"""
Unit tests for Notification Forwarder and Redis Pub/Sub Listener.
"""

import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from redis.exceptions import ResponseError

from services.gateway.config import GatewaySettings
from services.gateway.consumers.notification_forwarder import (
    NotificationForwarder,
    RedisPubSubListener,
    format_notification_message,
)
from services.gateway.ws.manager import WebSocketConnectionManager
from shared.events.envelope import EventEnvelope
from shared.events.event_types import (
    CG_GATEWAY_NOTIFY,
    EVENT_ALERT_APPROVED,
    EVENT_ALERT_BLOCKED,
    EVENT_ALERT_CREATED,
    EVENT_ALERT_FALSE_POSITIVE,
    EVENT_ESCALATION_EMAIL_REQUESTED,
    EVENT_ESCALATION_SLACK_REQUESTED,
    PUBSUB_NOTIFICATIONS,
    STREAM_ALERTS,
    STREAM_ESCALATIONS,
)


def test_format_notification_alert_created() -> None:
    payload = {
        "alert_id": "alt_123",
        "transaction_id": "txn_456",
        "status": "PENDING",
        "severity": "HIGH",
        "composite_risk_score": 0.88,
        "created_at": "2026-08-13T12:00:00Z",
    }
    formatted = format_notification_message(EVENT_ALERT_CREATED, payload)
    assert formatted is not None
    assert formatted["type"] == "alert.created"
    assert formatted["alert"]["id"] == "alt_123"
    assert formatted["alert"]["transaction_id"] == "txn_456"
    assert formatted["alert"]["status"] == "PENDING"
    assert formatted["alert"]["severity"] == "HIGH"
    assert formatted["alert"]["composite_risk_score"] == 0.88


def test_format_notification_alert_updated() -> None:
    payload = {
        "alert_id": "alt_123",
        "target_status": "BLOCKED",
        "resolved_at": "2026-08-13T12:05:00Z",
    }
    formatted = format_notification_message(EVENT_ALERT_BLOCKED, payload)
    assert formatted is not None
    assert formatted["type"] == "alert.updated"
    assert formatted["alert"]["id"] == "alt_123"
    assert formatted["alert"]["status"] == "BLOCKED"
    assert formatted["alert"]["resolved_at"] == "2026-08-13T12:05:00Z"


def test_format_notification_escalation_email() -> None:
    payload = {"alert_id": "alt_789"}
    formatted = format_notification_message(EVENT_ESCALATION_EMAIL_REQUESTED, payload)
    assert formatted is not None
    assert formatted["type"] == "escalation"
    assert formatted["alert_id"] == "alt_789"
    assert formatted["escalation_level"] == "email"


def test_format_notification_escalation_slack() -> None:
    payload = {"alert_id": "alt_789"}
    formatted = format_notification_message(EVENT_ESCALATION_SLACK_REQUESTED, payload)
    assert formatted is not None
    assert formatted["type"] == "escalation"
    assert formatted["alert_id"] == "alt_789"
    assert formatted["escalation_level"] == "slack"


@pytest.mark.asyncio
async def test_setup_consumer_groups() -> None:
    mock_redis = MagicMock()
    mock_redis.xgroup_create = AsyncMock()

    forwarder = NotificationForwarder()
    await forwarder.setup_consumer_groups(mock_redis)

    assert mock_redis.xgroup_create.await_count == 2


@pytest.mark.asyncio
async def test_setup_consumer_groups_handles_busygroup() -> None:
    mock_redis = MagicMock()
    mock_redis.xgroup_create = AsyncMock(side_effect=ResponseError("BUSYGROUP Consumer Group name already exists"))

    forwarder = NotificationForwarder()
    # Should not raise exception
    await forwarder.setup_consumer_groups(mock_redis)


@pytest.mark.asyncio
async def test_process_stream_message_success() -> None:
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock()
    mock_redis.xack = AsyncMock()

    forwarder = NotificationForwarder()

    envelope = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=EVENT_ALERT_CREATED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        correlation_id=str(uuid.uuid4()),
        producer_service="processor",
        payload={
            "alert_id": "alt_999",
            "transaction_id": "txn_888",
            "status": "PENDING",
            "severity": "CRITICAL",
            "composite_risk_score": 0.95,
        },
    )

    raw_msg_data = {"data": envelope.model_dump_json()}

    await forwarder.process_stream_message(
        redis_client=mock_redis,
        stream_name=STREAM_ALERTS,
        message_id="1600000000000-0",
        message_data=raw_msg_data,
    )

    mock_redis.publish.assert_awaited_once()
    mock_redis.xack.assert_awaited_once_with(
        STREAM_ALERTS,
        CG_GATEWAY_NOTIFY,
        "1600000000000-0",
    )


@pytest.mark.asyncio
async def test_process_stream_message_publish_error_no_xack() -> None:
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(side_effect=Exception("Pub/Sub connection broken"))
    mock_redis.xack = AsyncMock()

    forwarder = NotificationForwarder()

    envelope = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=EVENT_ALERT_CREATED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        correlation_id=str(uuid.uuid4()),
        producer_service="processor",
        payload={"alert_id": "alt_999"},
    )

    await forwarder.process_stream_message(
        redis_client=mock_redis,
        stream_name=STREAM_ALERTS,
        message_id="1600000000000-0",
        message_data={"data": envelope.model_dump_json()},
    )

    # Should attempt to publish but NOT acknowledge on failure
    mock_redis.publish.assert_awaited_once()
    mock_redis.xack.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_stream_message_invalid_payload_xacks() -> None:
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock()
    mock_redis.xack = AsyncMock()

    forwarder = NotificationForwarder()

    # Invalid JSON that cannot be parsed into EventEnvelope
    await forwarder.process_stream_message(
        redis_client=mock_redis,
        stream_name=STREAM_ALERTS,
        message_id="1600000000000-0",
        message_data={"data": "not-valid-json"},
    )

    # Invalid message should be ACKed to avoid infinite stall
    mock_redis.xack.assert_awaited_once_with(
        STREAM_ALERTS,
        CG_GATEWAY_NOTIFY,
        "1600000000000-0",
    )


@pytest.mark.asyncio
async def test_run_consumer_loop() -> None:
    mock_redis = MagicMock()
    mock_redis.xgroup_create = AsyncMock()
    mock_redis.publish = AsyncMock()
    mock_redis.xack = AsyncMock()

    envelope = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=EVENT_ESCALATION_EMAIL_REQUESTED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        correlation_id=str(uuid.uuid4()),
        producer_service="processor",
        payload={"alert_id": "alt_esc_1"},
    )

    # Return a batch once, then empty
    mock_redis.xreadgroup = AsyncMock(
        side_effect=[
            [
                (
                    STREAM_ESCALATIONS,
                    [("1600000000000-0", {"data": envelope.model_dump_json()})],
                )
            ],
            [],
        ]
    )

    forwarder = NotificationForwarder()
    shutdown_event = asyncio.Event()

    task = asyncio.create_task(
        forwarder.run_consumer_loop(
            redis_client=mock_redis,
            shutdown_event=shutdown_event,
        )
    )

    await asyncio.sleep(0.05)
    shutdown_event.set()
    await task

    mock_redis.publish.assert_awaited()
    mock_redis.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_autoclaim_loop() -> None:
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock()
    mock_redis.xack = AsyncMock()

    envelope = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=EVENT_ALERT_CREATED,
        event_version="1.0",
        occurred_at=datetime.now(timezone.utc),
        correlation_id=str(uuid.uuid4()),
        producer_service="processor",
        payload={"alert_id": "alt_autoclaim_1"},
    )


    mock_redis.xautoclaim = AsyncMock(
        return_value=(
            "0-0",
            [("1600000000000-0", {"data": envelope.model_dump_json()})],
            [],
        )
    )

    forwarder = NotificationForwarder(
        config=GatewaySettings(FORWARDER_AUTOCLAIM_INTERVAL_SECONDS=0.01)
    )


    shutdown_event = asyncio.Event()

    task = asyncio.create_task(
        forwarder.run_autoclaim_loop(
            redis_client=mock_redis,
            shutdown_event=shutdown_event,
        )
    )

    await asyncio.sleep(0.05)
    shutdown_event.set()
    await task

    mock_redis.xautoclaim.assert_awaited()
    mock_redis.publish.assert_awaited()
    mock_redis.xack.assert_awaited()


@pytest.mark.asyncio
async def test_redis_pubsub_listener() -> None:
    mock_pubsub = MagicMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()

    mock_pubsub.get_message = AsyncMock(
        side_effect=[
            {
                "type": "message",
                "data": json.dumps({"type": "alert.created", "alert": {"id": "alt_1"}}),
            },
            None,
        ]
    )

    mock_redis = MagicMock()
    mock_redis.pubsub.return_value = mock_pubsub

    mock_ws_manager = MagicMock(spec=WebSocketConnectionManager)
    mock_ws_manager.broadcast = AsyncMock(return_value=1)

    listener = RedisPubSubListener()
    shutdown_event = asyncio.Event()

    task = asyncio.create_task(
        listener.run_listener_loop(
            redis_client=mock_redis,
            ws_connection_manager=mock_ws_manager,
            shutdown_event=shutdown_event,
        )
    )

    await asyncio.sleep(0.05)
    shutdown_event.set()
    await task

    mock_pubsub.subscribe.assert_awaited_once_with(PUBSUB_NOTIFICATIONS)
    mock_ws_manager.broadcast.assert_awaited_once()
    mock_pubsub.unsubscribe.assert_awaited_once_with(PUBSUB_NOTIFICATIONS)
    mock_pubsub.aclose.assert_awaited_once()
