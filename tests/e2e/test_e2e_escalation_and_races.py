"""
End-to-end tests for escalation scheduler workflows and race condition resolution.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from services.processor.config import ProcessorSettings
from services.processor.scheduler.escalation_scheduler import EscalationScheduler
from shared.events.event_types import (
    EVENT_ESCALATION_EMAIL_REQUESTED,
    EVENT_ESCALATION_SLACK_REQUESTED,
)
from shared.models import Alert, AuditLog, OutboxEvent
from shared.models.enums import AlertSeverity, AlertStatus


@pytest.mark.asyncio
async def test_escalation_multitier_progression_fast_clock():
    """
    Executes multiple escalation ticks against manipulated alert timestamps:
    Tick 1: PENDING (older than email cutoff) -> ESCALATED_EMAIL + Outbox Event
    Tick 2: ESCALATED_EMAIL (older than slack cutoff) -> ESCALATED_SLACK + Outbox Event
    """
    scheduler = EscalationScheduler(
        settings=ProcessorSettings(
            ESCALATION_EMAIL_MINUTES=5,
            ESCALATION_SLACK_MINUTES=15,
        )
    )

    t0 = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    alert = Alert(
        id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=AlertStatus.PENDING.value,
        severity=AlertSeverity.CRITICAL.value,
        composite_risk_score=Decimal("0.9500"),
        correlation_id=uuid.uuid4(),
        created_at=t0 - timedelta(minutes=10),
    )

    # 1. Tick 1 (at t0): alert is 10 min old -> Escalates to EMAIL
    mock_email_q1 = MagicMock()
    mock_email_q1.scalars.return_value.all.return_value = [alert]
    mock_upd_1 = MagicMock()
    mock_upd_1.fetchone.return_value = MagicMock(
        id=alert.id,
        transaction_id=alert.transaction_id,
        user_id=alert.user_id,
        severity=alert.severity,
        composite_risk_score=alert.composite_risk_score,
        correlation_id=alert.correlation_id,
    )
    mock_slack_q1 = MagicMock()
    mock_slack_q1.scalars.return_value.all.return_value = []

    mock_session.execute.side_effect = [mock_email_q1, mock_upd_1, mock_slack_q1]

    e_count, s_count = await scheduler.run_escalation_tick(session=mock_session, current_time=t0)
    assert e_count == 1
    assert s_count == 0

    # 2. Tick 2 (at t0 + 20 min): alert was escalated to email, now older than slack cutoff -> Escalates to SLACK
    t1 = t0 + timedelta(minutes=20)
    alert.status = AlertStatus.ESCALATED_EMAIL.value
    alert.escalated_email_at = t0

    mock_email_q2 = MagicMock()
    mock_email_q2.scalars.return_value.all.return_value = []
    mock_slack_q2 = MagicMock()
    mock_slack_q2.scalars.return_value.all.return_value = [alert]
    mock_upd_2 = MagicMock()
    mock_upd_2.fetchone.return_value = MagicMock(
        id=alert.id,
        transaction_id=alert.transaction_id,
        user_id=alert.user_id,
        severity=alert.severity,
        composite_risk_score=alert.composite_risk_score,
        correlation_id=alert.correlation_id,
    )

    mock_session.execute.side_effect = [mock_email_q2, mock_slack_q2, mock_upd_2]

    e_count2, s_count2 = await scheduler.run_escalation_tick(session=mock_session, current_time=t1)
    assert e_count2 == 0
    assert s_count2 == 1


@pytest.mark.asyncio
async def test_concurrent_analyst_vs_scheduler_race_resolution():
    """
    Simulates concurrent analyst resolution and scheduler tick on the same alert:
    Conditional UPDATE WHERE status=PENDING ensures atomic win without contradictory states.
    """
    scheduler = EscalationScheduler()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    now = datetime.now(timezone.utc)

    alert_id = uuid.uuid4()
    alert = Alert(
        id=alert_id,
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=AlertStatus.PENDING.value,
        severity=AlertSeverity.HIGH.value,
        composite_risk_score=Decimal("0.8500"),
        correlation_id=uuid.uuid4(),
        created_at=now - timedelta(minutes=20),
    )

    # Scheduler queries pending alerts and finds row
    mock_email_q = MagicMock()
    mock_email_q.scalars.return_value.all.return_value = [alert]

    # In parallel, analyst's transaction commits: row status becomes APPROVED
    # Scheduler conditional UPDATE WHERE status = PENDING affects 0 rows
    mock_upd = MagicMock()
    mock_upd.fetchone.return_value = None

    mock_slack_q = MagicMock()
    mock_slack_q.scalars.return_value.all.return_value = []

    mock_session.execute.side_effect = [mock_email_q, mock_upd, mock_slack_q]

    # Scheduler tick completes gracefully with 0 escalations
    email_escalated, slack_escalated = await scheduler.run_escalation_tick(
        session=mock_session,
        current_time=now,
    )

    assert email_escalated == 0
    assert slack_escalated == 0
