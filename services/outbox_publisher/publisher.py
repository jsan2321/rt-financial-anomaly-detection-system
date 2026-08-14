"""
Core Transactional Outbox Publisher worker.
Polls PENDING outbox events with SKIP LOCKED and publishes to Redis Streams.
Instrumented with OpenTelemetry distributed trace spans and Prometheus metrics (NFR-OBS-002, NFR-OBS-004).
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Optional, Sequence
import uuid

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.session import DatabaseSessionManager
from shared.events.envelope import EventEnvelope
from shared.events.event_types import (
    STREAM_ALERTS,
    STREAM_COMPENSATION,
    STREAM_ESCALATIONS,
    STREAM_TRANSACTIONS,
)
from shared.logging.json_logger import get_json_logger
from shared.models import DeadLetterEvent, OutboxEvent
from shared.models.enums import OutboxStatus
from shared.telemetry import (
    extract_trace_context,
    inject_trace_context,
    outbox_dead_lettered_total,
    outbox_events_published_total,
    sample_outbox_backlog,
    trace_span,
)

from .config import OutboxPublisherSettings, settings as default_settings

logger = get_json_logger(__name__)


def get_stream_for_event_type(event_type: str) -> str:
    """
    Maps an event_type string to its designated Redis Stream topic.
    Conforms to SRS §7.2 and docs/api/event-contracts.md.
    """
    if event_type.startswith("transaction."):
        return STREAM_TRANSACTIONS
    elif event_type.startswith("alert."):
        return STREAM_ALERTS
    elif event_type.startswith("escalation."):
        return STREAM_ESCALATIONS
    elif event_type.startswith("risk_profile."):
        return STREAM_COMPENSATION

    # Fallback to prefix-based stream name
    prefix = event_type.split(".")[0] if "." in event_type else event_type
    return f"stream:{prefix}"


class OutboxPublisher:
    """
    Stateless worker service that polls and publishes OutboxEvent records to Redis Streams.
    """

    def __init__(self, settings: Optional[OutboxPublisherSettings] = None):
        self.settings = settings or default_settings

    async def poll_pending_events(
        self,
        session: AsyncSession,
        batch_size: int,
    ) -> Sequence[OutboxEvent]:
        """
        Fetches up to batch_size PENDING events using SELECT ... FOR UPDATE SKIP LOCKED.
        Safe for concurrent multi-replica execution (FR-EVT-006).
        """
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.status == OutboxStatus.PENDING.value)
            .order_by(OutboxEvent.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def publish_event(
        self,
        redis_client: aioredis.Redis,
        event: OutboxEvent,
    ) -> str:
        """
        Wraps OutboxEvent in standard EventEnvelope and publishes via Redis XADD.
        Extracts parent trace context and propagates trace carrier (NFR-OBS-002).
        Returns the Redis Stream message ID.
        """
        parent_ctx = None
        if isinstance(event.payload, dict) and "_trace_context" in event.payload:
            parent_ctx = extract_trace_context(event.payload["_trace_context"])

        with trace_span(
            "outbox.publish_event",
            attributes={
                "event_id": str(event.id),
                "event_type": event.event_type,
                "correlation_id": str(event.correlation_id),
            },
            parent_context=parent_ctx,
        ):
            stream_name = get_stream_for_event_type(event.event_type)

            # Ensure trace context is injected into envelope payload
            payload_data = dict(event.payload) if isinstance(event.payload, dict) else {"data": event.payload}
            if "_trace_context" not in payload_data:
                carrier: dict = {}
                inject_trace_context(carrier)
                payload_data["_trace_context"] = carrier

            envelope = EventEnvelope(
                event_id=str(event.id),
                correlation_id=str(event.correlation_id),
                event_type=event.event_type,
                event_version=event.event_version,
                occurred_at=event.created_at,
                producer_service=event.producer_service,
                payload=payload_data,
            )

            msg_id = await redis_client.xadd(
                name=stream_name,
                fields={
                    "event": envelope.to_json(),
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                },
            )

            outbox_events_published_total.inc(event_type=event.event_type)
            return msg_id if isinstance(msg_id, str) else msg_id.decode("utf-8")

    def handle_publish_failure(
        self,
        session: AsyncSession,
        event: OutboxEvent,
        error: Exception,
    ) -> None:
        """
        Handles publication failures with retry increment or dead-letter queue escalation (FR-EVT-005).
        """
        event.retry_count += 1
        stream_name = get_stream_for_event_type(event.event_type)

        if event.retry_count >= self.settings.MAX_RETRIES:
            logger.error(
                f"OutboxEvent {event.id} ({event.event_type}) exceeded max retries "
                f"({event.retry_count}/{self.settings.MAX_RETRIES}). Moving to DeadLetterEvent.",
                extra={
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "correlation_id": str(event.correlation_id),
                },
                exc_info=True,
            )
            event.status = OutboxStatus.DEAD_LETTERED.value

            dlq_event = DeadLetterEvent(
                id=uuid.uuid4(),
                original_event_id=event.id,
                event_type=event.event_type,
                payload=event.payload,
                error_message=str(error),
                retry_count=event.retry_count,
                stream_name=stream_name,
                consumer_group=None,
                created_at=datetime.now(timezone.utc),
            )
            session.add(dlq_event)
            outbox_dead_lettered_total.inc(stream=stream_name)
        else:
            logger.warning(
                f"Failed to publish OutboxEvent {event.id} ({event.event_type}) on attempt "
                f"{event.retry_count}/{self.settings.MAX_RETRIES}: {str(error)}. Will retry.",
                extra={"event_id": str(event.id), "event_type": event.event_type},
            )

    async def publish_batch(
        self,
        session: AsyncSession,
        redis_client: aioredis.Redis,
    ) -> int:
        """
        Executes a single poll-publish-mark cycle.
        Returns the number of events processed in this batch.
        """
        events = await self.poll_pending_events(session, self.settings.BATCH_SIZE)
        if not events:
            return 0

        success_count = 0
        now = datetime.now(timezone.utc)

        with trace_span("outbox.publish_batch", attributes={"batch_size": len(events)}):
            for event in events:
                try:
                    msg_id = await self.publish_event(redis_client, event)
                    event.status = OutboxStatus.PUBLISHED.value
                    event.published_at = now
                    success_count += 1
                    logger.info(
                        f"Published event {event.id} ({event.event_type}) to Redis stream",
                        extra={
                            "event_id": str(event.id),
                            "event_type": event.event_type,
                            "correlation_id": str(event.correlation_id),
                            "stream_msg_id": msg_id,
                        },
                    )
                except Exception as exc:
                    self.handle_publish_failure(session, event, exc)

            await session.commit()
        return len(events)

    async def run_loop(
        self,
        db_manager: DatabaseSessionManager,
        redis_client: aioredis.Redis,
        shutdown_event: asyncio.Event,
    ) -> None:
        """
        Continuous worker loop polling the outbox and publishing events.
        Exits gracefully when shutdown_event is set.
        """
        logger.info("Starting Outbox Publisher polling loop")

        while not shutdown_event.is_set():
            try:
                async with db_manager.session_factory() as session:
                    # Sample outbox backlog gauge (NFR-OBS-005)
                    await sample_outbox_backlog(session, service="outbox_publisher")
                    processed_count = await self.publish_batch(session, redis_client)

                # If no events were pending, pause before next poll interval
                if processed_count == 0:
                    try:
                        await asyncio.wait_for(
                            shutdown_event.wait(),
                            timeout=self.settings.POLL_INTERVAL_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        pass
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Unexpected error in outbox polling loop: {exc}", exc_info=True)
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=self.settings.BACKOFF_BASE_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass

        logger.info("Outbox Publisher polling loop terminated cleanly")
