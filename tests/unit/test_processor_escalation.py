"""
Unit tests for Processor EscalationScheduler.
Tests time-based multi-tier alert escalations, AuditLog generation, OutboxEvent creation,
and race condition silent no-op handling.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
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


@pytest.fixture
def scheduler_settings() -> ProcessorSettings:
    return ProcessorSettings(
        ESCALATION_POLL_SECONDS=0.1,
        ESCALATION_EMAIL_MINUTES=5.0,
        ESCALATION_SLACK_MINUTES=10.0,
        ESCALATION_BATCH_SIZE=50,
    )


@pytest.fixture
def scheduler(scheduler_settings) -> EscalationScheduler:
    return EscalationScheduler(settings=scheduler_settings)


@pytest.mark.asyncio
async def test_escalation_email_tier_success(scheduler):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    now = datetime.now(timezone.utc)
    created_at = now - timedelta(minutes=6)  # Older than 5m email threshold

    alert_id = uuid.uuid4()
    txn_id = uuid.uuid4()
    user_id = uuid.uuid4()
    corr_id = uuid.uuid4()

    pending_alert = Alert(
        id=alert_id,
        transaction_id=txn_id,
        user_id=user_id,
        status=AlertStatus.PENDING.value,
        severity=AlertSeverity.HIGH.value,
        composite_risk_score=Decimal("0.8000"),
        correlation_id=corr_id,
        created_at=created_at,
    )

    # 1. Email query returns the pending alert
    mock_email_res = MagicMock()
    mock_email_res.scalars.return_value.all.return_value = [pending_alert]

    # 2. Update RETURNING row
    mock_row = MagicMock(
        id=alert_id,
        transaction_id=txn_id,
        user_id=user_id,
        severity=AlertSeverity.HIGH.value,
        composite_risk_score=Decimal("0.8000"),
        correlation_id=corr_id,
    )
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = mock_row

    # 3. Slack query returns no alerts
    mock_slack_res = MagicMock()
    mock_slack_res.scalars.return_value.all.return_value = []

    mock_session.execute.side_effect = [
        mock_email_res,    # SELECT PENDING
        mock_update_res,   # UPDATE to ESCALATED_EMAIL
        mock_slack_res,    # SELECT ESCALATED_EMAIL
    ]

    email_count, slack_count = await scheduler.run_escalation_tick(
        session=mock_session,
        current_time=now,
    )

    assert email_count == 1
    assert slack_count == 0

    added_objects = [call[0][0] for call in mock_session.add.call_args_list]

    # Verify AuditLog created
    audit_logs = [obj for obj in added_objects if isinstance(obj, AuditLog)]
    assert len(audit_logs) == 1
    assert audit_logs[0].actor == "system:escalation_scheduler"
    assert audit_logs[0].action == "alert.escalated_email"
    assert audit_logs[0].entity_id == str(alert_id)
    assert audit_logs[0].after["status"] == AlertStatus.ESCALATED_EMAIL.value

    # Verify OutboxEvent created
    outbox_events = [obj for obj in added_objects if isinstance(obj, OutboxEvent)]
    assert len(outbox_events) == 1
    assert outbox_events[0].event_type == EVENT_ESCALATION_EMAIL_REQUESTED
    assert outbox_events[0].producer_service == "processor"
    assert outbox_events[0].payload["alert_id"] == str(alert_id)
    assert outbox_events[0].payload["status"] == AlertStatus.ESCALATED_EMAIL.value
    assert outbox_events[0].payload["escalation_type"] == "email"

    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_escalation_slack_tier_success(scheduler):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    now = datetime.now(timezone.utc)
    escalated_email_at = now - timedelta(minutes=12)  # Older than 10m slack threshold

    alert_id = uuid.uuid4()
    txn_id = uuid.uuid4()
    user_id = uuid.uuid4()
    corr_id = uuid.uuid4()

    email_alert = Alert(
        id=alert_id,
        transaction_id=txn_id,
        user_id=user_id,
        status=AlertStatus.ESCALATED_EMAIL.value,
        severity=AlertSeverity.CRITICAL.value,
        composite_risk_score=Decimal("0.9500"),
        escalated_email_at=escalated_email_at,
        correlation_id=corr_id,
        created_at=now - timedelta(minutes=20),
    )

    # 1. Email query returns no alerts
    mock_email_res = MagicMock()
    mock_email_res.scalars.return_value.all.return_value = []

    # 2. Slack query returns email_alert
    mock_slack_res = MagicMock()
    mock_slack_res.scalars.return_value.all.return_value = [email_alert]

    # 3. Update RETURNING row
    mock_row = MagicMock(
        id=alert_id,
        transaction_id=txn_id,
        user_id=user_id,
        severity=AlertSeverity.CRITICAL.value,
        composite_risk_score=Decimal("0.9500"),
        correlation_id=corr_id,
    )
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = mock_row

    mock_session.execute.side_effect = [
        mock_email_res,    # SELECT PENDING
        mock_slack_res,    # SELECT ESCALATED_EMAIL
        mock_update_res,   # UPDATE to ESCALATED_SLACK
    ]

    email_count, slack_count = await scheduler.run_escalation_tick(
        session=mock_session,
        current_time=now,
    )

    assert email_count == 0
    assert slack_count == 1

    added_objects = [call[0][0] for call in mock_session.add.call_args_list]

    # Verify AuditLog created
    audit_logs = [obj for obj in added_objects if isinstance(obj, AuditLog)]
    assert len(audit_logs) == 1
    assert audit_logs[0].actor == "system:escalation_scheduler"
    assert audit_logs[0].action == "alert.escalated_slack"
    assert audit_logs[0].entity_id == str(alert_id)
    assert audit_logs[0].after["status"] == AlertStatus.ESCALATED_SLACK.value

    # Verify OutboxEvent created
    outbox_events = [obj for obj in added_objects if isinstance(obj, OutboxEvent)]
    assert len(outbox_events) == 1
    assert outbox_events[0].event_type == EVENT_ESCALATION_SLACK_REQUESTED
    assert outbox_events[0].producer_service == "processor"
    assert outbox_events[0].payload["alert_id"] == str(alert_id)
    assert outbox_events[0].payload["status"] == AlertStatus.ESCALATED_SLACK.value
    assert outbox_events[0].payload["escalation_type"] == "slack"

    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_alerts_within_time_window_not_escalated(scheduler):
    mock_session = AsyncMock()

    # Both queries return empty lists
    mock_email_res = MagicMock()
    mock_email_res.scalars.return_value.all.return_value = []
    mock_slack_res = MagicMock()
    mock_slack_res.scalars.return_value.all.return_value = []

    mock_session.execute.side_effect = [mock_email_res, mock_slack_res]

    email_count, slack_count = await scheduler.run_escalation_tick(mock_session)

    assert email_count == 0
    assert slack_count == 0
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_escalation_race_condition_silent_noop(scheduler):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    now = datetime.now(timezone.utc)
    alert = Alert(
        id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=AlertStatus.PENDING.value,
        severity=AlertSeverity.HIGH.value,
        composite_risk_score=Decimal("0.7000"),
        created_at=now - timedelta(minutes=7),
    )

    # 1. Alert found in SELECT
    mock_email_res = MagicMock()
    mock_email_res.scalars.return_value.all.return_value = [alert]

    # 2. UPDATE returns None (analyst resolved it in the meantime, 0 rows affected)
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = None

    # 3. Slack query
    mock_slack_res = MagicMock()
    mock_slack_res.scalars.return_value.all.return_value = []

    mock_session.execute.side_effect = [
        mock_email_res,
        mock_update_res,
        mock_slack_res,
    ]

    # Should execute without error, treating race as silent no-op (FR-ESC-006)
    email_count, slack_count = await scheduler.run_escalation_tick(
        session=mock_session,
        current_time=now,
    )

    assert email_count == 0
    assert slack_count == 0
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_escalation_scheduler_loop_cancellation(scheduler):
    mock_db_manager = MagicMock()
    mock_session = AsyncMock()
    mock_db_manager.session_factory.return_value.__aenter__.return_value = mock_session

    mock_email_res = MagicMock()
    mock_email_res.scalars.return_value.all.return_value = []
    mock_slack_res = MagicMock()
    mock_slack_res.scalars.return_value.all.return_value = []
    mock_session.execute.side_effect = lambda stmt: mock_email_res

    shutdown_event = asyncio.Event()

    task = asyncio.create_task(
        scheduler.run_scheduler_loop(
            db_manager=mock_db_manager,
            shutdown_event=shutdown_event,
        )
    )

    await asyncio.sleep(0.15)
    shutdown_event.set()
    await task
