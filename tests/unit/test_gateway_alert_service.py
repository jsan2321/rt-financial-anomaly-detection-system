"""
Unit tests for Gateway AlertActionService.
Tests alert queries, race-safe conditional transitions, audit logging, and outbox event creation.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from services.gateway.services.alert_actions import AlertActionService
from shared.errors.exceptions import (
    InvalidStateTransitionError,
    ResourceNotFoundError,
    ValidationError,
)
from shared.events.event_types import (
    EVENT_ALERT_APPROVED,
    EVENT_ALERT_BLOCKED,
    EVENT_ALERT_FALSE_POSITIVE,
    EVENT_RISK_PROFILE_RECALCULATE,
)
from shared.models import Alert, AuditLog, OutboxEvent
from shared.models.enums import AlertSeverity, AlertStatus


@pytest.fixture
def alert_service() -> AlertActionService:
    return AlertActionService()


@pytest.mark.asyncio
async def test_get_alerts_pagination_and_filtering(alert_service):
    mock_session = AsyncMock()

    # Total count query mock
    mock_count_res = MagicMock()
    mock_count_res.scalar_one.return_value = 2

    # Items query mock
    alert1 = Alert(
        id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="PENDING",
        severity="HIGH",
        composite_risk_score=Decimal("0.7500"),
        is_demo=False,
        created_at=datetime.now(timezone.utc),
    )
    alert2 = Alert(
        id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="PENDING",
        severity="CRITICAL",
        composite_risk_score=Decimal("0.9000"),
        is_demo=True,
        created_at=datetime.now(timezone.utc),
    )

    mock_items_res = MagicMock()
    mock_items_res.scalars.return_value.all.return_value = [alert1, alert2]

    mock_session.execute.side_effect = [mock_count_res, mock_items_res]

    resp = await alert_service.get_alerts(
        session=mock_session,
        status=AlertStatus.PENDING,
        severity=AlertSeverity.HIGH,
        page=1,
        page_size=10,
    )

    assert resp.total == 2
    assert len(resp.items) == 2
    assert resp.items[0].status == AlertStatus.PENDING
    assert resp.items[1].is_demo is True


@pytest.mark.asyncio
async def test_get_alert_by_id_success(alert_service):
    mock_session = AsyncMock()
    alert_id = uuid.uuid4()
    alert = Alert(
        id=alert_id,
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="PENDING",
        severity="HIGH",
        composite_risk_score=Decimal("0.7500"),
        ml_anomaly_score=Decimal("0.6000"),
        rule_matches=[{"name": "Rule"}],
        risk_profile_snapshot={},
        is_demo=False,
        correlation_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = alert
    mock_session.execute.return_value = mock_res

    resp = await alert_service.get_alert_by_id(mock_session, alert_id)
    assert resp.id == alert_id
    assert resp.status == AlertStatus.PENDING
    assert resp.severity == AlertSeverity.HIGH


@pytest.mark.asyncio
async def test_get_alert_by_id_not_found(alert_service):
    mock_session = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res

    with pytest.raises(ResourceNotFoundError):
        await alert_service.get_alert_by_id(mock_session, uuid.uuid4())


@pytest.mark.asyncio
async def test_resolve_alert_approve_success(alert_service):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    alert_id = uuid.uuid4()
    txn_id = uuid.uuid4()
    user_id = uuid.uuid4()
    corr_id = str(uuid.uuid4())

    # Return row from UPDATE ... RETURNING
    mock_row = MagicMock(
        id=alert_id,
        transaction_id=txn_id,
        user_id=user_id,
        status="APPROVED",
        severity="HIGH",
    )
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = mock_row
    mock_session.execute.return_value = mock_update_res

    resp = await alert_service.resolve_alert(
        session=mock_session,
        alert_id=alert_id,
        target_status=AlertStatus.APPROVED,
        actor="analyst_alice",
        correlation_id=corr_id,
        resolution_reason="Confirmed genuine purchase",
    )

    assert resp.alert_id == alert_id
    assert resp.status == AlertStatus.APPROVED
    assert resp.resolved_by == "analyst_alice"
    assert resp.resolution_reason == "Confirmed genuine purchase"

    added_objects = [call[0][0] for call in mock_session.add.call_args_list]

    # 1. AuditLog added
    audit_logs = [obj for obj in added_objects if isinstance(obj, AuditLog)]
    assert len(audit_logs) == 1
    assert audit_logs[0].actor == "analyst_alice"
    assert audit_logs[0].action == "alert.approved"
    assert audit_logs[0].entity_id == str(alert_id)

    # 2. alert.approved OutboxEvent added
    outbox_events = [obj for obj in added_objects if isinstance(obj, OutboxEvent)]
    assert len(outbox_events) == 1
    assert outbox_events[0].event_type == EVENT_ALERT_APPROVED
    assert outbox_events[0].payload["alert_id"] == str(alert_id)
    assert outbox_events[0].payload["status"] == "APPROVED"

    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_alert_false_positive_emits_compensation_event(alert_service):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    alert_id = uuid.uuid4()
    txn_id = uuid.uuid4()
    user_id = uuid.uuid4()
    corr_id = str(uuid.uuid4())

    mock_row = MagicMock(
        id=alert_id,
        transaction_id=txn_id,
        user_id=user_id,
        status="FALSE_POSITIVE",
        severity="HIGH",
    )
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = mock_row
    mock_session.execute.return_value = mock_update_res

    resp = await alert_service.resolve_alert(
        session=mock_session,
        alert_id=alert_id,
        target_status=AlertStatus.FALSE_POSITIVE,
        actor="analyst_bob",
        correlation_id=corr_id,
        resolution_reason="False alarm",
    )

    assert resp.status == AlertStatus.FALSE_POSITIVE

    added_objects = [call[0][0] for call in mock_session.add.call_args_list]

    # Verify 2 outbox events: alert.false_positive + risk_profile.recalculate (FR-COMP-001)
    outbox_events = [obj for obj in added_objects if isinstance(obj, OutboxEvent)]
    assert len(outbox_events) == 2

    fp_event = next(e for e in outbox_events if e.event_type == EVENT_ALERT_FALSE_POSITIVE)
    assert fp_event.payload["alert_id"] == str(alert_id)

    comp_event = next(e for e in outbox_events if e.event_type == EVENT_RISK_PROFILE_RECALCULATE)
    assert comp_event.payload["user_id"] == str(user_id)
    assert comp_event.payload["alert_id"] == str(alert_id)

    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_alert_lost_race_raises_409_conflict(alert_service):
    mock_session = AsyncMock()

    # Conditional update matches 0 rows (lost race)
    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = None

    # Secondary check finds alert already APPROVED by another analyst
    existing_alert = Alert(
        id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=AlertStatus.APPROVED.value,
        severity=AlertSeverity.HIGH.value,
    )
    mock_check_res = MagicMock()
    mock_check_res.scalar_one_or_none.return_value = existing_alert

    mock_session.execute.side_effect = [mock_update_res, mock_check_res]

    alert_id = existing_alert.id
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        await alert_service.resolve_alert(
            session=mock_session,
            alert_id=alert_id,
            target_status=AlertStatus.BLOCKED,
            actor="analyst_charlie",
            correlation_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 409
    assert "Cannot transition alert" in exc_info.value.message


@pytest.mark.asyncio
async def test_resolve_alert_not_found_raises_404(alert_service):
    mock_session = AsyncMock()

    mock_update_res = MagicMock()
    mock_update_res.fetchone.return_value = None

    mock_check_res = MagicMock()
    mock_check_res.scalar_one_or_none.return_value = None

    mock_session.execute.side_effect = [mock_update_res, mock_check_res]

    non_existent_id = uuid.uuid4()
    with pytest.raises(ResourceNotFoundError):
        await alert_service.resolve_alert(
            session=mock_session,
            alert_id=non_existent_id,
            target_status=AlertStatus.APPROVED,
            actor="analyst_alice",
            correlation_id=str(uuid.uuid4()),
        )


@pytest.mark.asyncio
async def test_resolve_alert_invalid_target_status_raises_validation_error(alert_service):
    mock_session = AsyncMock()

    with pytest.raises(ValidationError):
        await alert_service.resolve_alert(
            session=mock_session,
            alert_id=uuid.uuid4(),
            target_status=AlertStatus.PENDING,  # PENDING is not a valid resolution target
            actor="analyst_alice",
            correlation_id=str(uuid.uuid4()),
        )
