"""
Notification forwarder consuming Redis Streams (stream:alerts, stream:escalations)
and relaying events to Redis Pub/Sub (ws:notifications) for WebSocket broadcast.
"""

import asyncio
from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

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
from shared.logging.json_logger import get_json_logger

from ..config import GatewaySettings, settings
from ..ws.manager import WebSocketConnectionManager

logger = get_json_logger(__name__)


def format_notification_message(event_type: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Transforms backend event envelope payloads into the standard client notification JSON schema.
    """
    if event_type == EVENT_ALERT_CREATED:
        return {
            "type": "alert.created",
            "alert": {
                "id": str(payload.get("alert_id") or payload.get("id", "")),
                "transaction_id": str(payload.get("transaction_id", "")),
                "status": payload.get("status", "PENDING"),
                "severity": payload.get("severity", "MEDIUM"),
                "composite_risk_score": payload.get("composite_risk_score", 0.0),
                "created_at": payload.get("created_at") or datetime.now(timezone.utc).isoformat(),
            },
        }

    if event_type in (EVENT_ALERT_APPROVED, EVENT_ALERT_BLOCKED, EVENT_ALERT_FALSE_POSITIVE) or event_type.startswith("alert."):
        # Determine updated status from event type if not explicitly in payload
        default_status = "PENDING"
        if event_type == EVENT_ALERT_APPROVED:
            default_status = "APPROVED"
        elif event_type == EVENT_ALERT_BLOCKED:
            default_status = "BLOCKED"
        elif event_type == EVENT_ALERT_FALSE_POSITIVE:
            default_status = "FALSE_POSITIVE"

        status_val = payload.get("target_status") or payload.get("status") or default_status
        return {
            "type": "alert.updated",
            "alert": {
                "id": str(payload.get("alert_id") or payload.get("id", "")),
                "status": status_val,
                "resolved_at": payload.get("resolved_at") or datetime.now(timezone.utc).isoformat(),
            },
        }

    if event_type == EVENT_ESCALATION_EMAIL_REQUESTED:
        return {
            "type": "escalation",
            "alert_id": str(payload.get("alert_id") or payload.get("id", "")),
            "escalation_level": "email",
        }

    if event_type == EVENT_ESCALATION_SLACK_REQUESTED:
        return {
            "type": "escalation",
            "alert_id": str(payload.get("alert_id") or payload.get("id", "")),
            "escalation_level": "slack",
        }

    # Generic notification fallback
    return {
        "type": event_type,
        "payload": payload,
    }


def parse_event_envelope(fields: Dict[str, Any]) -> EventEnvelope[Dict[str, Any]]:
    """Parses standard EventEnvelope from Redis stream message fields."""
    if "event" in fields:
        raw = fields["event"]
        return EventEnvelope.from_json(raw) if isinstance(raw, str) else EventEnvelope.from_dict(raw)
    elif "envelope" in fields:
        raw = fields["envelope"]
        return EventEnvelope.from_json(raw) if isinstance(raw, str) else EventEnvelope.from_dict(raw)
    elif "data" in fields:
        raw = fields["data"]
        return EventEnvelope.from_json(raw) if isinstance(raw, str) else EventEnvelope.from_dict(raw)
    else:
        return EventEnvelope.from_dict(fields)


class NotificationForwarder:
    """
    Consumes durable events from Redis Streams via the gateway consumer group,
    formats them into WebSocket payloads, and publishes to Redis Pub/Sub.
    """

    def __init__(self, config: Optional[GatewaySettings] = None) -> None:
        self.settings = config or settings
        self.consumer_name = f"{self.settings.APP_NAME}-forwarder"
        self.streams = [self.settings.STREAM_ALERTS, self.settings.STREAM_ESCALATIONS]

    async def setup_consumer_groups(self, redis_client: aioredis.Redis) -> None:
        """
        Idempotently initializes Redis Streams and consumer groups.
        """
        for stream in self.streams:
            try:
                await redis_client.xgroup_create(
                    name=stream,
                    groupname=self.settings.GROUP_GATEWAY_NOTIFY,
                    id="0",
                    mkstream=True,
                )
                logger.info(
                    f"Created consumer group {self.settings.GROUP_GATEWAY_NOTIFY} on stream {stream}"
                )
            except ResponseError as err:
                if "BUSYGROUP" in str(err):
                    logger.debug(
                        f"Consumer group {self.settings.GROUP_GATEWAY_NOTIFY} already exists on {stream}"
                    )
                else:
                    logger.error(f"Error creating consumer group on {stream}: {err}")
                    raise

    async def process_stream_message(
        self,
        redis_client: aioredis.Redis,
        stream_name: str,
        message_id: str,
        message_data: Dict[str, Any],
    ) -> None:
        """
        Deserializes stream event, publishes formatted payload to Pub/Sub, and sends XACK.
        """
        try:
            envelope = parse_event_envelope(message_data)
        except Exception as parse_err:
            logger.error(
                f"Failed to parse EventEnvelope from message {message_id} on {stream_name}: {parse_err}",
                extra={"message_data": message_data},
            )
            # Acknowledge unparseable messages to avoid infinite blocking
            await redis_client.xack(stream_name, self.settings.GROUP_GATEWAY_NOTIFY, message_id)
            return

        notification = format_notification_message(envelope.event_type, envelope.payload)


        if notification is not None:
            notification_str = json.dumps(notification)
            try:
                await redis_client.publish(
                    self.settings.PUBSUB_NOTIFICATIONS,
                    notification_str,
                )
                logger.debug(
                    f"Forwarded event {envelope.event_id} ({envelope.event_type}) to Pub/Sub {self.settings.PUBSUB_NOTIFICATIONS}",
                    extra={
                        "event_id": envelope.event_id,
                        "event_type": envelope.event_type,
                        "correlation_id": envelope.correlation_id,
                    },
                )
            except Exception as pub_err:
                logger.error(
                    f"Failed to publish to Pub/Sub {self.settings.PUBSUB_NOTIFICATIONS}: {pub_err}",
                    exc_info=True,
                )
                # Do not XACK on Redis communication failure; message will be redelivered
                return

        # Acknowledge successful forwarding
        await redis_client.xack(stream_name, self.settings.GROUP_GATEWAY_NOTIFY, message_id)

    async def run_consumer_loop(
        self,
        redis_client: aioredis.Redis,
        shutdown_event: asyncio.Event,
    ) -> None:
        """
        Continuously polls Redis Streams and relays alert/escalation events to Pub/Sub.
        """
        await self.setup_consumer_groups(redis_client)
        logger.info(
            "Starting NotificationForwarder consumer loop",
            extra={
                "streams": self.streams,
                "consumer_group": self.settings.GROUP_GATEWAY_NOTIFY,
                "pubsub_channel": self.settings.PUBSUB_NOTIFICATIONS,
            },
        )

        streams_dict = {stream: ">" for stream in self.streams}

        while not shutdown_event.is_set():
            try:
                entries = await redis_client.xreadgroup(
                    groupname=self.settings.GROUP_GATEWAY_NOTIFY,
                    consumername=self.consumer_name,
                    streams=streams_dict,
                    count=self.settings.FORWARDER_BATCH_SIZE,
                    block=self.settings.FORWARDER_BLOCK_MS,
                )

                if not entries:
                    continue

                for stream_name, messages in entries:
                    for message_id, message_data in messages:
                        if shutdown_event.is_set():
                            break
                        await self.process_stream_message(
                            redis_client=redis_client,
                            stream_name=stream_name,
                            message_id=message_id,
                            message_data=message_data,
                        )

            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.error(f"Error in NotificationForwarder consumer loop: {err}", exc_info=True)
                await asyncio.sleep(1.0)

        logger.info("NotificationForwarder consumer loop stopped")

    async def run_autoclaim_loop(
        self,
        redis_client: aioredis.Redis,
        shutdown_event: asyncio.Event,
    ) -> None:
        """
        Periodically runs XAUTOCLAIM to reclaim orphaned messages from crashed consumers.
        """
        logger.info(
            "Starting NotificationForwarder XAUTOCLAIM loop",
            extra={"streams": self.streams},
        )

        while not shutdown_event.is_set():
            try:
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=float(self.settings.FORWARDER_AUTOCLAIM_INTERVAL_SECONDS),
                    )
                    break
                except asyncio.TimeoutError:
                    pass

                for stream_name in self.streams:
                    start_id = "0-0"
                    while not shutdown_event.is_set():
                        try:
                            result = await redis_client.xautoclaim(
                                name=stream_name,
                                groupname=self.settings.GROUP_GATEWAY_NOTIFY,
                                consumername=self.consumer_name,
                                min_idle_time=self.settings.FORWARDER_AUTOCLAIM_IDLE_MS,
                                start_id=start_id,
                                count=self.settings.FORWARDER_BATCH_SIZE,
                            )
                            # result format: [next_start_id, [ (msg_id, data), ... ], [deleted_ids...]]
                            next_start_id = result[0]
                            claimed_messages = result[1]

                            for message_id, message_data in claimed_messages:
                                if shutdown_event.is_set():
                                    break
                                if message_data:
                                    logger.info(
                                        f"Reclaimed orphaned message {message_id} from {stream_name}",
                                        extra={"stream": stream_name, "message_id": message_id},
                                    )
                                    await self.process_stream_message(
                                        redis_client=redis_client,
                                        stream_name=stream_name,
                                        message_id=message_id,
                                        message_data=message_data,
                                    )

                            if next_start_id == "0-0" or not claimed_messages:
                                break
                            start_id = next_start_id
                        except Exception as claim_err:
                            logger.error(
                                f"Error in XAUTOCLAIM for stream {stream_name}: {claim_err}",
                                exc_info=True,
                            )
                            break

            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.error(f"Unhandled error in XAUTOCLAIM loop: {err}", exc_info=True)
                await asyncio.sleep(1.0)

        logger.info("NotificationForwarder XAUTOCLAIM loop stopped")


class RedisPubSubListener:
    """
    Subscribes to the ephemeral Redis Pub/Sub channel and broadcasts
    received notification payloads to all connected WebSocket clients.
    """

    def __init__(self, config: Optional[GatewaySettings] = None) -> None:
        self.settings = config or settings

    async def run_listener_loop(
        self,
        redis_client: aioredis.Redis,
        ws_connection_manager: WebSocketConnectionManager,
        shutdown_event: asyncio.Event,
    ) -> None:
        """
        Listens on ws:notifications and broadcasts messages via WebSocketConnectionManager.
        """
        logger.info(
            "Starting Redis Pub/Sub listener loop",
            extra={"channel": self.settings.PUBSUB_NOTIFICATIONS},
        )

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(self.settings.PUBSUB_NOTIFICATIONS)

        try:
            while not shutdown_event.is_set():
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    if message and message.get("type") == "message":
                        data = message.get("data")
                        if data:
                            delivered = await ws_connection_manager.broadcast(data)
                            logger.debug(
                                f"Broadcasted Pub/Sub notification to {delivered} active WebSocket clients"
                            )
                except asyncio.CancelledError:
                    break
                except Exception as err:
                    logger.error(f"Error in Redis Pub/Sub listener: {err}", exc_info=True)
                    await asyncio.sleep(0.5)
        finally:
            logger.info("Stopping Redis Pub/Sub listener loop")
            try:
                await pubsub.unsubscribe(self.settings.PUBSUB_NOTIFICATIONS)
                await pubsub.aclose()
            except Exception as cleanup_err:
                logger.debug(f"Error closing pubsub subscriber: {cleanup_err}")
