"""
Redis Streams consumer for processing stream:compensation events (processor-compensation-group).
Recalculates user risk profiles idempotently with inbox deduplication, XAUTOCLAIM crash recovery,
and post-commit XACK.
"""

import asyncio
from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional
import uuid

import redis.asyncio as aioredis
from redis.exceptions import ResponseError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.context.correlation import set_correlation_id
from shared.db.session import DatabaseSessionManager
from shared.events.envelope import EventEnvelope
from shared.events.event_types import (
    CG_PROCESSOR_COMPENSATION,
    EVENT_RISK_PROFILE_RECALCULATE,
    STREAM_COMPENSATION,
    STREAM_DLQ_PREFIX,
)
from shared.logging.json_logger import get_json_logger
from shared.models import DeadLetterEvent, ProcessedEvent

from ..config import ProcessorSettings, settings as default_settings
from ..services.compensation_service import RiskCompensationService

logger = get_json_logger(__name__)


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


class CompensationConsumer:
    """Consumer for processing risk_profile.recalculate events from stream:compensation."""

    def __init__(
        self,
        compensation_service: Optional[RiskCompensationService] = None,
        settings: Optional[ProcessorSettings] = None,
    ) -> None:
        self.compensation_service = compensation_service or RiskCompensationService()
        self.settings = settings or default_settings
        self.consumer_group = self.settings.GROUP_COMPENSATION or CG_PROCESSOR_COMPENSATION
        self.stream_key = self.settings.STREAM_COMPENSATION or STREAM_COMPENSATION

    async def setup_consumer_group(self, redis_client: aioredis.Redis) -> None:
        """Initializes the Redis stream and consumer group if they do not exist."""
        try:
            await redis_client.xgroup_create(
                name=self.stream_key,
                groupname=self.consumer_group,
                id="$",
                mkstream=True,
            )
            logger.info(
                f"Created consumer group '{self.consumer_group}' on stream '{self.stream_key}'"
            )
        except ResponseError as err:
            if "BUSYGROUP" in str(err):
                logger.debug(
                    f"Consumer group '{self.consumer_group}' already exists on '{self.stream_key}'"
                )
            else:
                logger.error(f"Error creating consumer group: {err}", exc_info=True)
                raise

    async def is_event_processed(
        self,
        session: AsyncSession,
        event_id: uuid.UUID,
    ) -> bool:
        """Verifies if an event has already been processed using the ProcessedEvent inbox."""
        stmt = select(ProcessedEvent).where(
            ProcessedEvent.event_id == event_id,
            ProcessedEvent.consumer_group == self.consumer_group,
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
        """Records poison pills exceeding max retry deliveries into the dead_letter_events table."""
        logger.error(
            f"Message {message_id} on {stream_key} exceeded max deliveries ({delivery_count}). Dead-lettering.",
            extra={"message_id": message_id, "stream": stream_key, "error": error_msg},
        )
        try:
            envelope = parse_event_envelope(fields)
            event_id = uuid.UUID(envelope.event_id)
            event_type = envelope.event_type
            payload = envelope.payload
        except Exception:
            event_id = uuid.uuid4()
            event_type = "unknown.compensation"
            payload = dict(fields)

        async with db_manager.session_factory() as session:
            dead_letter = DeadLetterEvent(
                id=uuid.uuid4(),
                original_event_id=event_id,
                event_type=event_type,
                payload=payload,
                error_message=error_msg,
                retry_count=delivery_count,
                stream_name=stream_key,
                consumer_group=self.consumer_group,
                created_at=datetime.now(timezone.utc),
            )
            session.add(dead_letter)
            await session.commit()

        # Publish to DLQ stream for monitoring and XACK original
        try:
            await redis_client.xadd(
                f"{STREAM_DLQ_PREFIX}:{stream_key.split(':')[-1]}",
                {"message_id": message_id, "error": error_msg, "fields": json.dumps(fields, default=str)},
            )
        except Exception:
            pass

        await redis_client.xack(stream_key, self.consumer_group, message_id)

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
        Idempotently processes a single risk_profile.recalculate event.
        Guarantees that XACK is sent strictly after the database commit.
        """
        # 1. Poison-pill check
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
        except Exception as parse_err:
            logger.error(f"Failed to parse compensation event envelope {message_id}: {parse_err}", exc_info=True)
            await self.handle_dead_letter(
                db_manager=db_manager,
                redis_client=redis_client,
                stream_key=stream_key,
                message_id=message_id,
                fields=fields,
                error_msg=f"Invalid event schema: {parse_err}",
                delivery_count=delivery_count,
            )
            return True

        # 3. Idempotent business processing in database transaction
        async with db_manager.session_factory() as session:
            # Check inbox
            if await self.is_event_processed(session, event_uuid):
                logger.info(
                    f"Compensation event {event_uuid} already processed by {self.consumer_group}. Skipping.",
                    extra={"event_id": str(event_uuid), "message_id": message_id},
                )
                await redis_client.xack(stream_key, self.consumer_group, message_id)
                return True

            try:
                data = envelope.payload
                user_id_str = data.get("user_id")
                alert_id_str = data.get("alert_id")

                if not user_id_str:
                    logger.warning(f"Compensation event {event_uuid} missing user_id. Skipping.")
                    return False

                user_uuid = uuid.UUID(user_id_str)
                alert_uuid = uuid.UUID(alert_id_str) if alert_id_str else None

                # Recalculate RiskProfile
                await self.compensation_service.recalculate_user_risk_profile(
                    session=session,
                    user_id=user_uuid,
                    alert_id=alert_uuid,
                )

                # Record into ProcessedEvent inbox
                processed_row = ProcessedEvent(
                    event_id=event_uuid,
                    consumer_group=self.consumer_group,
                    processed_at=datetime.now(timezone.utc),
                )
                session.add(processed_row)

                # Commit DB transaction atomically
                await session.commit()

            except Exception as proc_err:
                await session.rollback()
                logger.error(
                    f"Error processing compensation event {event_uuid}: {proc_err}",
                    extra={"event_id": str(event_uuid), "message_id": message_id},
                    exc_info=True,
                )
                # Do NOT acknowledge message; leaves it pending for retry / crash recovery
                return False

        # 4. XACK sent strictly after successful commit
        await redis_client.xack(stream_key, self.consumer_group, message_id)
        logger.info(
            f"Successfully processed and acknowledged compensation event {event_uuid}",
            extra={"event_id": str(event_uuid), "message_id": message_id},
        )
        return True

    async def run_autoclaim_loop(
        self,
        db_manager: DatabaseSessionManager,
        redis_client: aioredis.Redis,
        shutdown_event: asyncio.Event,
    ) -> None:
        """Periodic background task executing XAUTOCLAIM for stalled compensation messages."""
        logger.info("Starting compensation consumer XAUTOCLAIM background loop")
        while not shutdown_event.is_set():
            try:
                cursor = "0-0"
                while cursor != "0-0" or cursor == "0-0":
                    autoclaim_res = await redis_client.xautoclaim(
                        name=self.stream_key,
                        groupname=self.consumer_group,
                        consumername=self.settings.CONSUMER_NAME,
                        min_idle_time=self.settings.AUTOCLAIM_MIN_IDLE_TIME_MS,
                        start_id=cursor,
                        count=self.settings.CONSUMER_BATCH_SIZE,
                    )
                    next_cursor, messages = autoclaim_res[0], autoclaim_res[1]
                    for msg in messages:
                        msg_id = msg[0]
                        fields = msg[1]
                        logger.warning(
                            f"XAUTOCLAIM recovered abandoned compensation message {msg_id}",
                            extra={"message_id": msg_id, "stream": self.stream_key},
                        )
                        await self.process_single_message(
                            db_manager=db_manager,
                            redis_client=redis_client,
                            stream_key=self.stream_key,
                            message_id=msg_id,
                            fields=fields,
                            delivery_count=2,
                        )

                    cursor = next_cursor
                    if cursor == "0-0" or not messages:
                        break

                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=self.settings.AUTOCLAIM_INTERVAL_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in compensation XAUTOCLAIM loop: {exc}", exc_info=True)
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass

        logger.info("Compensation XAUTOCLAIM background loop terminated")

    async def run_consumer_loop(
        self,
        db_manager: DatabaseSessionManager,
        redis_client: aioredis.Redis,
        shutdown_event: asyncio.Event,
    ) -> None:
        """Main polling loop for stream:compensation."""
        await self.setup_consumer_group(redis_client)
        logger.info(
            f"Starting compensation consumer loop on {self.stream_key} ({self.consumer_group}) as {self.settings.CONSUMER_NAME}"
        )

        while not shutdown_event.is_set():
            try:
                response = await redis_client.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.settings.CONSUMER_NAME,
                    streams={self.stream_key: ">"},
                    count=self.settings.CONSUMER_BATCH_SIZE,
                    block=self.settings.CONSUMER_BLOCK_MS,
                )

                if not response:
                    continue

                for stream_name, messages in response:
                    for message_id, fields in messages:
                        await self.process_single_message(
                            db_manager=db_manager,
                            redis_client=redis_client,
                            stream_key=stream_name,
                            message_id=message_id,
                            fields=fields,
                            delivery_count=1,
                        )

            except asyncio.CancelledError:
                break
            except Exception as loop_err:
                logger.error(f"Unexpected error in compensation consumer loop: {loop_err}", exc_info=True)
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass

        logger.info("Compensation consumer loop terminated cleanly")
