"""
Escalation scheduler for RT-FADS Processor service.
Periodically scans unhandled alerts and executes race-safe multi-tier status transitions:
PENDING -> ESCALATED_EMAIL -> ESCALATED_SLACK.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.session import DatabaseSessionManager
from shared.events.event_types import (
    DEFAULT_EVENT_VERSION,
    EVENT_ESCALATION_EMAIL_REQUESTED,
    EVENT_ESCALATION_SLACK_REQUESTED,
)
from shared.logging.json_logger import get_json_logger
from shared.models import Alert, AuditLog, OutboxEvent
from shared.models.enums import AlertStatus, OutboxStatus

from ..config import ProcessorSettings, settings as default_settings

logger = get_json_logger(__name__)


class EscalationScheduler:
    """In-process scheduler managing time-based alert escalations."""

    def __init__(self, settings: Optional[ProcessorSettings] = None) -> None:
        self.settings = settings or default_settings

    async def run_escalation_tick(
        self,
        session: AsyncSession,
        current_time: Optional[datetime] = None,
    ) -> Tuple[int, int]:
        """
        Executes a single escalation evaluation tick for both email and Slack tiers.
        Safe for multi-replica concurrency via SELECT ... FOR UPDATE SKIP LOCKED.
        Lost races with analyst resolutions are treated as benign silent no-ops.
        Returns (email_escalated_count, slack_escalated_count).
        """
        now = current_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        email_escalated_count = 0
        slack_escalated_count = 0

        # ----------------------------------------------------------------------
        # 1. Tier 1: PENDING -> ESCALATED_EMAIL
        # ----------------------------------------------------------------------
        email_cutoff = now - timedelta(minutes=self.settings.ESCALATION_EMAIL_MINUTES)
        email_stmt = (
            select(Alert)
            .where(
                Alert.status == AlertStatus.PENDING.value,
                Alert.created_at <= email_cutoff,
            )
            .order_by(Alert.created_at.asc())
            .limit(self.settings.ESCALATION_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        email_result = await session.execute(email_stmt)
        pending_alerts = email_result.scalars().all()

        for alert in pending_alerts:
            update_stmt = (
                update(Alert)
                .where(
                    Alert.id == alert.id,
                    Alert.status == AlertStatus.PENDING.value,
                )
                .values(
                    status=AlertStatus.ESCALATED_EMAIL.value,
                    escalated_email_at=now,
                )
                .returning(
                    Alert.id,
                    Alert.transaction_id,
                    Alert.user_id,
                    Alert.severity,
                    Alert.composite_risk_score,
                    Alert.correlation_id,
                )
            )
            upd_res = await session.execute(update_stmt)
            updated_row = upd_res.fetchone()

            if updated_row is None:
                # Lost race: an analyst resolved the alert or another tick handled it
                # Silent no-op
                continue

            # 1a. Write AuditLog row
            audit_log = AuditLog(
                id=uuid.uuid4(),
                actor="system:escalation_scheduler",
                action="alert.escalated_email",
                entity_type="Alert",
                entity_id=str(updated_row.id),
                before={"status": AlertStatus.PENDING.value},
                after={
                    "status": AlertStatus.ESCALATED_EMAIL.value,
                    "escalated_email_at": now.isoformat(),
                },
                correlation_id=updated_row.correlation_id,
                created_at=now,
            )
            session.add(audit_log)

            # 1b. Write escalation.email.requested OutboxEvent
            outbox_payload = {
                "alert_id": str(updated_row.id),
                "transaction_id": str(updated_row.transaction_id),
                "user_id": str(updated_row.user_id),
                "status": AlertStatus.ESCALATED_EMAIL.value,
                "severity": updated_row.severity,
                "composite_risk_score": str(updated_row.composite_risk_score),
                "escalation_type": "email",
                "escalated_at": now.isoformat(),
            }
            outbox_event = OutboxEvent(
                id=uuid.uuid4(),
                event_type=EVENT_ESCALATION_EMAIL_REQUESTED,
                event_version=DEFAULT_EVENT_VERSION,
                payload=outbox_payload,
                correlation_id=updated_row.correlation_id,
                producer_service="processor",
                status=OutboxStatus.PENDING.value,
                retry_count=0,
                created_at=now,
            )
            session.add(outbox_event)
            email_escalated_count += 1

            logger.info(
                f"Escalated alert {updated_row.id} to ESCALATED_EMAIL",
                extra={
                    "alert_id": str(updated_row.id),
                    "status": AlertStatus.ESCALATED_EMAIL.value,
                    "correlation_id": str(updated_row.correlation_id),
                },
            )

        # ----------------------------------------------------------------------
        # 2. Tier 2: ESCALATED_EMAIL -> ESCALATED_SLACK
        # ----------------------------------------------------------------------
        slack_cutoff = now - timedelta(minutes=self.settings.ESCALATION_SLACK_MINUTES)
        slack_stmt = (
            select(Alert)
            .where(
                Alert.status == AlertStatus.ESCALATED_EMAIL.value,
                Alert.escalated_email_at <= slack_cutoff,
            )
            .order_by(Alert.escalated_email_at.asc())
            .limit(self.settings.ESCALATION_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        slack_result = await session.execute(slack_stmt)
        email_alerts = slack_result.scalars().all()

        for alert in email_alerts:
            update_stmt = (
                update(Alert)
                .where(
                    Alert.id == alert.id,
                    Alert.status == AlertStatus.ESCALATED_EMAIL.value,
                )
                .values(
                    status=AlertStatus.ESCALATED_SLACK.value,
                    escalated_slack_at=now,
                )
                .returning(
                    Alert.id,
                    Alert.transaction_id,
                    Alert.user_id,
                    Alert.severity,
                    Alert.composite_risk_score,
                    Alert.correlation_id,
                )
            )
            upd_res = await session.execute(update_stmt)
            updated_row = upd_res.fetchone()

            if updated_row is None:
                # Lost race: silent no-op
                continue

            # 2a. Write AuditLog row
            audit_log = AuditLog(
                id=uuid.uuid4(),
                actor="system:escalation_scheduler",
                action="alert.escalated_slack",
                entity_type="Alert",
                entity_id=str(updated_row.id),
                before={"status": AlertStatus.ESCALATED_EMAIL.value},
                after={
                    "status": AlertStatus.ESCALATED_SLACK.value,
                    "escalated_slack_at": now.isoformat(),
                },
                correlation_id=updated_row.correlation_id,
                created_at=now,
            )
            session.add(audit_log)

            # 2b. Write escalation.slack.requested OutboxEvent
            outbox_payload = {
                "alert_id": str(updated_row.id),
                "transaction_id": str(updated_row.transaction_id),
                "user_id": str(updated_row.user_id),
                "status": AlertStatus.ESCALATED_SLACK.value,
                "severity": updated_row.severity,
                "composite_risk_score": str(updated_row.composite_risk_score),
                "escalation_type": "slack",
                "escalated_at": now.isoformat(),
            }
            outbox_event = OutboxEvent(
                id=uuid.uuid4(),
                event_type=EVENT_ESCALATION_SLACK_REQUESTED,
                event_version=DEFAULT_EVENT_VERSION,
                payload=outbox_payload,
                correlation_id=updated_row.correlation_id,
                producer_service="processor",
                status=OutboxStatus.PENDING.value,
                retry_count=0,
                created_at=now,
            )
            session.add(outbox_event)
            slack_escalated_count += 1

            logger.info(
                f"Escalated alert {updated_row.id} to ESCALATED_SLACK",
                extra={
                    "alert_id": str(updated_row.id),
                    "status": AlertStatus.ESCALATED_SLACK.value,
                    "correlation_id": str(updated_row.correlation_id),
                },
            )

        # Commit all transitions, audit records, and outbox events atomically
        if email_escalated_count > 0 or slack_escalated_count > 0:
            await session.commit()

        return email_escalated_count, slack_escalated_count

    async def run_scheduler_loop(
        self,
        db_manager: DatabaseSessionManager,
        shutdown_event: asyncio.Event,
    ) -> None:
        """
        Continuous background worker loop polling for alerts eligible for escalation.
        """
        logger.info(
            "Starting Processor escalation scheduler loop",
            extra={
                "poll_interval_sec": self.settings.ESCALATION_POLL_SECONDS,
                "email_threshold_min": self.settings.ESCALATION_EMAIL_MINUTES,
                "slack_threshold_min": self.settings.ESCALATION_SLACK_MINUTES,
            },
        )

        while not shutdown_event.is_set():
            try:
                async with db_manager.session_factory() as session:
                    email_count, slack_count = await self.run_escalation_tick(session)
                    if email_count > 0 or slack_count > 0:
                        logger.info(
                            f"Escalation tick completed: {email_count} email, {slack_count} slack",
                            extra={"email_count": email_count, "slack_count": slack_count},
                        )

                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=self.settings.ESCALATION_POLL_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in escalation scheduler tick: {exc}", exc_info=True)
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass

        logger.info("Processor escalation scheduler loop terminated cleanly")
