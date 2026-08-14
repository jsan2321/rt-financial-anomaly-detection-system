"""
Redis Streams consumer for transaction events in RT-FADS Processor.
Implements consumer group consumption, inbox idempotency (ProcessedEvent),
XAUTOCLAIM crash recovery, dead-letter thresholding, and post-commit XACK.
"""

import asyncio
from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional, Tuple
import uuid

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.context.correlation import set_correlation_id
from shared.db.session import DatabaseSessionManager
from shared.events.envelope import EventEnvelope
from shared.events.event_types import STREAM_DLQ_PREFIX
from shared.logging.json_logger import get_json_logger
from shared.models import DeadLetterEvent, ProcessedEvent
from shared.telemetry import (
    extract_trace_context,
    outbox_dead_lettered_total,
    processing_failures_total,
    processing_latency_seconds,
    sample_stream_backlog,
    trace_span,
    transactions_processed_total,
)

from ..config import ProcessorSettings, settings as default_settings
from ..services.detection_pipeline import DetectionPipeline

logger = get_json_logger(__name__)


def parse_event_envelope(fields: Dict[str, Any]) -> EventEnvelope[Dict[str, Any]]:
    """Parses standard EventEnvelope from Redis stream message fields."""
    if "event" in fields:
        raw = fields["event"]
        return EventEnvelope.from_json(raw) if isinstance(raw, str) else EventEnvelope.from_dict(raw)
    elif "envelope" in fields:
        raw = fields["envelope"]
        return EventEnvelope.from_json(raw) if isinstance(raw, str) else EventEnvelope.from_dict(raw)
    else:
        return EventEnvelope.from_dict(fields)


class TransactionConsumer:
    """Consumes transactions from Redis Streams and coordinates idempotent detection."""

    def __init__(
        self,
        pipeline: DetectionPipeline,
        settings: Optional[ProcessorSettings] = None,
    ) -> None:
        self.pipeline = pipeline
        self.settings = settings or default_settings

    async def setup_consumer_group(self, redis_client: aioredis.Redis) -> None:
        """
        Creates consumer group on the transactions stream if it does not already exist.
        """
        try:
            await redis_client.xgroup_create(
                name=self.settings.STREAM_TRANSACTIONS,
                groupname=self.settings.GROUP_TRANSACTIONS,
                id="$",
                mkstream=True,
            )
            logger.info(
                "Initialized Redis consumer group",
                extra={
                    "stream": self.settings.STREAM_TRANSACTIONS,
                    "group": self.settings.GROUP_TRANSACTIONS,
                },
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                logger.debug(
                    "Consumer group already exists",
                    extra={
                        "stream": self.settings.STREAM_TRANSACTIONS,
                        "group": self.settings.GROUP_TRANSACTIONS,
                    },
                )
            else:
                logger.error(f"Failed to create consumer group: {exc}", exc_info=True)
                raise

    async def is_event_processed(
        self,
        session: AsyncSession,
        event_id: uuid.UUID,
    ) -> bool:
        """
        Queries ProcessedEvent table to determine if event_id was already committed.
        """
        stmt = select(ProcessedEvent).where(
            ProcessedEvent.event_id == event_id,
            ProcessedEvent.consumer_group == self.settings.GROUP_TRANSACTIONS,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def handle_dead_letter(
        self,
        db_manager: DatabaseSessionManager,
        redis_client: aioredis.Redis,
        stream_key: str,
        message_id: str,
        fields: Dict[str, Any],
        error_msg: str,
        delivery_count: int,
    ) -> None:
        """
        Records dead letter row and sends XACK to remove poison pill from stream.
        """
        logger.error(
            "Transaction message exceeded max delivery attempts. Dead-lettering.",
            extra={
                "message_id": message_id,
                "stream": stream_key,
                "delivery_count": delivery_count,
                "error": error_msg,
            },
        )
        try:
            envelope = parse_event_envelope(fields)
            event_id = uuid.UUID(envelope.event_id)
            event_type = envelope.event_type
            payload = envelope.payload
        except Exception:
            event_id = uuid.uuid4()
            event_type = "unknown.transaction"
            payload = dict(fields)

        async with db_manager.session_factory() as session:
            dlq_event = DeadLetterEvent(
                id=uuid.uuid4(),
                original_event_id=event_id,
                event_type=event_type,
                payload=payload,
                error_message=error_msg,
                retry_count=delivery_count,
                stream_name=stream_key,
                consumer_group=self.settings.GROUP_TRANSACTIONS,
                created_at=datetime.now(timezone.utc),
            )
            session.add(dlq_event)
            await session.commit()

        # Publish to DLQ stream for monitoring and XACK original
        try:
            await redis_client.xadd(
                f"{STREAM_DLQ_PREFIX}:{stream_key.split(':')[-1]}",
                {"message_id": message_id, "error": error_msg, "fields": json.dumps(fields, default=str)},
            )
        except Exception:
            pass

        outbox_dead_lettered_total.inc(stream=stream_key)
        await redis_client.xack(stream_key, self.settings.GROUP_TRANSACTIONS, message_id)

    async def process_single_message(
        self,
        db_manager: DatabaseSessionManager,
        redis_client: aioredis.Redis,
        stream_key: str,
        message_id: str,
        fields: Dict[str, Any],
        delivery_count: int = 1,
    ) -> bool:
        """
        Processes a single Redis stream message with inbox idempotency, OpenTelemetry tracing, and post-commit XACK.
        """
        # 1. Check delivery threshold for poison pill prevention
        if delivery_count > self.settings.MAX_CONSUMER_DELIVERIES:
            await self.handle_dead_letter(
                db_manager=db_manager,
                redis_client=redis_client,
                stream_key=stream_key,
                message_id=message_id,
                fields=fields,
                error_msg=f"Exceeded max deliveries ({delivery_count}/{self.settings.MAX_CONSUMER_DELIVERIES})",
                delivery_count=delivery_count,
            )
            return True

        # 2. Parse envelope
        try:
            envelope = parse_event_envelope(fields)
            event_uuid = uuid.UUID(envelope.event_id)
            set_correlation_id(envelope.correlation_id)
        except Exception as ex:
            logger.error(
                f"Failed to parse event envelope from stream message {message_id}: {ex}",
                extra={"message_id": message_id},
                exc_info=True,
            )
            await self.handle_dead_letter(
                db_manager=db_manager,
                redis_client=redis_client,
                stream_key=stream_key,
                message_id=message_id,
                fields=fields,
                error_msg=f"Corrupt event envelope: {str(ex)}",
                delivery_count=delivery_count,
            )
            return True

        # Extract parent trace context from envelope payload or stream fields
        parent_ctx = None
        if isinstance(envelope.payload, dict) and "_trace_context" in envelope.payload:
            parent_ctx = extract_trace_context(envelope.payload["_trace_context"])
        elif "traceparent" in fields:
            parent_ctx = extract_trace_context(fields)

        # 3. Idempotent processing in DB session with distributed trace span
        with trace_span(
            "processor.consume_transaction",
            attributes={
                "event_id": str(event_uuid),
                "correlation_id": envelope.correlation_id,
                "consumer_group": self.settings.GROUP_TRANSACTIONS,
                "stream": stream_key,
            },
            parent_context=parent_ctx,
        ):
            with processing_latency_seconds.time(stage="pipeline_total"):
                try:
                    async with db_manager.session_factory() as session:
                        # 3a. Inbox check (FR-EVT-007, §7.3)
                        if await self.is_event_processed(session, event_uuid):
                            logger.info(
                                "Duplicate event detected in inbox; skipping business logic and acknowledging",
                                extra={"event_id": str(event_uuid), "message_id": message_id},
                            )
                            transactions_processed_total.inc(status="duplicate_inbox")
                            # Acknowledge immediately since already committed
                            await redis_client.xack(stream_key, self.settings.GROUP_TRANSACTIONS, message_id)
                            return True

                        # 3b. Execute detection pipeline (commits DB transaction on success)
                        await self.pipeline.process_transaction_event(
                            session=session,
                            event_envelope=envelope,
                        )

                    # 4. Acknowledge message ONLY AFTER DB commit succeeds (FR-EVT-009)
                    await redis_client.xack(stream_key, self.settings.GROUP_TRANSACTIONS, message_id)
                    transactions_processed_total.inc(status="completed")
                    logger.debug(
                        "Acknowledged stream message post-commit",
                        extra={"event_id": str(event_uuid), "message_id": message_id},
                    )
                    return True

                except Exception as exc:
                    processing_failures_total.inc(stage="pipeline")
                    transactions_processed_total.inc(status="failed")
                    logger.error(
                        f"Error processing transaction event {event_uuid}: {exc}. Will not XACK.",
                        extra={"event_id": str(event_uuid), "message_id": message_id},
                        exc_info=True,
                    )
                    # Do NOT XACK: message remains pending for XAUTOCLAIM / retry
                    return False

    async def run_autoclaim_loop(
        self,
        db_manager: DatabaseSessionManager,
        redis_client: aioredis.Redis,
        shutdown_event: asyncio.Event,
    ) -> None:
        """
        Periodic background task running XAUTOCLAIM to recover stalled pending messages (FR-EVT-010).
        """
        logger.info(
            "Starting XAUTOCLAIM recovery loop",
            extra={"interval_sec": self.settings.AUTOCLAIM_INTERVAL_SECONDS},
        )

        start_id = "0-0"
        while not shutdown_event.is_set():
            try:
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=self.settings.AUTOCLAIM_INTERVAL_SECONDS,
                    )
                    break
                except asyncio.TimeoutError:
                    pass

                # Reclaim pending messages idle longer than min_idle_time
                claim_result = await redis_client.xautoclaim(
                    name=self.settings.STREAM_TRANSACTIONS,
                    groupname=self.settings.GROUP_TRANSACTIONS,
                    consumername=self.settings.CONSUMER_NAME,
                    min_idle_time=self.settings.AUTOCLAIM_MIN_IDLE_TIME_MS,
                    start_id=start_id,
                    count=50,
                )

                if claim_result:
                    start_id = claim_result[0] if isinstance(claim_result, (list, tuple)) else "0-0"
                    messages = claim_result[1] if len(claim_result) > 1 else []

                    if messages:
                        logger.info(
                            f"XAUTOCLAIM reclaimed {len(messages)} pending message(s)",
                            extra={"count": len(messages)},
                        )
                        for msg_id, fields in messages:
                            msg_id_str = msg_id if isinstance(msg_id, str) else msg_id.decode("utf-8")
                            await self.process_single_message(
                                db_manager=db_manager,
                                redis_client=redis_client,
                                stream_key=self.settings.STREAM_TRANSACTIONS,
                                message_id=msg_id_str,
                                fields=fields,
                                delivery_count=2,  # Reclaimed messages have been delivered >= 2 times
                            )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in XAUTOCLAIM loop: {exc}", exc_info=True)

        logger.info("XAUTOCLAIM loop terminated cleanly")

    async def run_consumer_loop(
        self,
        db_manager: DatabaseSessionManager,
        redis_client: aioredis.Redis,
        shutdown_event: asyncio.Event,
    ) -> None:
        """
        Continuous stream consumer loop reading new messages via XREADGROUP.
        """
        logger.info(
            "Starting Processor transaction consumer loop",
            extra={
                "stream": self.settings.STREAM_TRANSACTIONS,
                "group": self.settings.GROUP_TRANSACTIONS,
                "consumer": self.settings.CONSUMER_NAME,
            },
        )

        await self.setup_consumer_group(redis_client)

        while not shutdown_event.is_set():
            try:
                # Sample stream backlog (NFR-OBS-005)
                await sample_stream_backlog(
                    redis_client=redis_client,
                    stream_name=self.settings.STREAM_TRANSACTIONS,
                    group_name=self.settings.GROUP_TRANSACTIONS,
                )

                streams_dict = {self.settings.STREAM_TRANSACTIONS: ">"}
                entries = await redis_client.xreadgroup(
                    groupname=self.settings.GROUP_TRANSACTIONS,
                    consumername=self.settings.CONSUMER_NAME,
                    streams=streams_dict,
                    count=self.settings.CONSUMER_BATCH_SIZE,
                    block=self.settings.CONSUMER_BLOCK_MS,
                )

                if not entries:
                    continue

                for stream_name, messages in entries:
                    stream_str = (
                        stream_name if isinstance(stream_name, str) else stream_name.decode("utf-8")
                    )
                    for msg_id, fields in messages:
                        msg_id_str = msg_id if isinstance(msg_id, str) else msg_id.decode("utf-8")
                        await self.process_single_message(
                            db_manager=db_manager,
                            redis_client=redis_client,
                            stream_key=stream_str,
                            message_id=msg_id_str,
                            fields=fields,
                            delivery_count=1,
                        )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error reading from Redis Stream: {exc}", exc_info=True)
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass

        logger.info("Processor transaction consumer loop terminated cleanly")
