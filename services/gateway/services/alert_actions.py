"""
Alert action and lifecycle management service for RT-FADS Gateway.
Handles alert listing, detail retrieval, and atomic race-safe state transitions.
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.errors.exceptions import (
    ConflictError,
    InvalidStateTransitionError,
    ResourceNotFoundError,
    ValidationError,
)
from shared.events.event_types import (
    DEFAULT_EVENT_VERSION,
    EVENT_ALERT_APPROVED,
    EVENT_ALERT_BLOCKED,
    EVENT_ALERT_FALSE_POSITIVE,
    EVENT_RISK_PROFILE_RECALCULATE,
)
from shared.logging.json_logger import get_json_logger
from shared.models import Alert, AuditLog, OutboxEvent
from shared.models.enums import AlertSeverity, AlertStatus, OutboxStatus

from ..schemas.alerts import (
    AlertDetailResponse,
    AlertListResponse,
    AlertResolutionResponse,
    AlertSummaryItem,
)

logger = get_json_logger(__name__)

# Valid non-terminal statuses eligible for analyst resolution (FR-ALERT-003)
VALID_PRE_RESOLUTION_STATUSES = (
    AlertStatus.PENDING.value,
    AlertStatus.ESCALATED_EMAIL.value,
    AlertStatus.ESCALATED_SLACK.value,
)

# Resolution status to event_type mapping
RESOLUTION_EVENT_MAP = {
    AlertStatus.APPROVED: EVENT_ALERT_APPROVED,
    AlertStatus.BLOCKED: EVENT_ALERT_BLOCKED,
    AlertStatus.FALSE_POSITIVE: EVENT_ALERT_FALSE_POSITIVE,
}


class AlertActionService:
    """Service providing analyst actions, queries, and state machine transitions for alerts."""

    async def get_alerts(
        self,
        session: AsyncSession,
        status: Optional[AlertStatus] = None,
        severity: Optional[AlertSeverity] = None,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> AlertListResponse:
        """
        Retrieves a paginated list of alerts filtered by status, severity, and date range (FR-ALERT-007).
        """
        query_conditions = []
        if status:
            query_conditions.append(Alert.status == status.value)
        if severity:
            query_conditions.append(Alert.severity == severity.value)
        if from_time:
            query_conditions.append(Alert.created_at >= from_time)
        if to_time:
            query_conditions.append(Alert.created_at <= to_time)

        # 1. Count total matching records
        count_stmt = select(func.count(Alert.id))
        if query_conditions:
            count_stmt = count_stmt.where(*query_conditions)
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one() or 0

        # 2. Fetch paginated records
        offset = (page - 1) * page_size
        items_stmt = (
            select(Alert)
            .order_by(Alert.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        if query_conditions:
            items_stmt = items_stmt.where(*query_conditions)

        items_result = await session.execute(items_stmt)
        alert_rows = items_result.scalars().all()

        items = [
            AlertSummaryItem(
                id=row.id,
                transaction_id=row.transaction_id,
                user_id=row.user_id,
                status=AlertStatus(row.status),
                severity=AlertSeverity(row.severity),
                composite_risk_score=row.composite_risk_score,
                is_demo=row.is_demo,
                created_at=row.created_at,
            )
            for row in alert_rows
        ]

        return AlertListResponse(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_alert_by_id(
        self,
        session: AsyncSession,
        alert_id: uuid.UUID,
    ) -> AlertDetailResponse:
        """
        Retrieves full explanation and decision detail for a specific alert (FR-ALERT-008).
        """
        stmt = select(Alert).where(Alert.id == alert_id)
        result = await session.execute(stmt)
        alert = result.scalar_one_or_none()

        if not alert:
            raise ResourceNotFoundError("Alert", str(alert_id))

        return AlertDetailResponse(
            id=alert.id,
            transaction_id=alert.transaction_id,
            user_id=alert.user_id,
            status=AlertStatus(alert.status),
            severity=AlertSeverity(alert.severity),
            composite_risk_score=alert.composite_risk_score,
            ml_anomaly_score=alert.ml_anomaly_score,
            rule_matches=alert.rule_matches or [],
            risk_profile_snapshot=alert.risk_profile_snapshot or {},
            is_demo=alert.is_demo,
            resolved_by=alert.resolved_by,
            resolved_at=alert.resolved_at,
            resolution_reason=alert.resolution_reason,
            escalated_email_at=alert.escalated_email_at,
            escalated_slack_at=alert.escalated_slack_at,
            correlation_id=alert.correlation_id,
            created_at=alert.created_at,
        )

    async def resolve_alert(
        self,
        session: AsyncSession,
        alert_id: uuid.UUID,
        target_status: AlertStatus,
        actor: str,
        correlation_id: str,
        resolution_reason: Optional[str] = None,
    ) -> AlertResolutionResponse:
        """
        Transitions an alert to a terminal resolved state (APPROVED, BLOCKED, FALSE_POSITIVE).
        Executes a race-safe conditional SQL update, creates an AuditLog record, and emits OutboxEvents.
        """
        if target_status not in (AlertStatus.APPROVED, AlertStatus.BLOCKED, AlertStatus.FALSE_POSITIVE):
            raise ValidationError(
                f"Invalid resolution target status '{target_status}'. Must be APPROVED, BLOCKED, or FALSE_POSITIVE."
            )

        now = datetime.now(timezone.utc)
        corr_uuid = (
            uuid.UUID(correlation_id)
            if isinstance(correlation_id, str)
            else correlation_id
        )

        # 1. Race-safe conditional UPDATE statement (FR-ALERT-006)
        update_stmt = (
            update(Alert)
            .where(
                Alert.id == alert_id,
                Alert.status.in_(VALID_PRE_RESOLUTION_STATUSES),
            )
            .values(
                status=target_status.value,
                resolved_by=actor,
                resolved_at=now,
                resolution_reason=resolution_reason,
            )
            .returning(
                Alert.id,
                Alert.transaction_id,
                Alert.user_id,
                Alert.status,
                Alert.severity,
            )
        )

        result = await session.execute(update_stmt)
        updated_row = result.fetchone()

        # 2. Handle lost race or missing record
        if updated_row is None:
            check_stmt = select(Alert).where(Alert.id == alert_id)
            check_result = await session.execute(check_stmt)
            existing_alert = check_result.scalar_one_or_none()

            if existing_alert is None:
                raise ResourceNotFoundError("Alert", str(alert_id))

            # Alert exists but was in an invalid status for resolution
            logger.warning(
                "Attempted invalid alert resolution transition",
                extra={
                    "alert_id": str(alert_id),
                    "current_status": existing_alert.status,
                    "target_status": target_status.value,
                },
            )
            raise InvalidStateTransitionError(
                current_status=existing_alert.status,
                target_status=target_status.value,
                entity_id=str(alert_id),
            )

        # 3. Append AuditLog entry (FR-ALERT-005)
        audit_log = AuditLog(
            id=uuid.uuid4(),
            actor=actor,
            action=f"alert.{target_status.value.lower()}",
            entity_type="Alert",
            entity_id=str(alert_id),
            before={"status": "UNRESOLVED"},
            after={
                "status": target_status.value,
                "resolved_by": actor,
                "resolution_reason": resolution_reason,
            },
            correlation_id=corr_uuid,
            created_at=now,
        )
        session.add(audit_log)

        # 4. Insert Resolution OutboxEvent
        event_type = RESOLUTION_EVENT_MAP[target_status]
        outbox_payload = {
            "alert_id": str(alert_id),
            "transaction_id": str(updated_row.transaction_id),
            "user_id": str(updated_row.user_id),
            "status": target_status.value,
            "severity": updated_row.severity,
            "resolved_by": actor,
            "resolved_at": now.isoformat(),
            "resolution_reason": resolution_reason,
        }

        outbox_event = OutboxEvent(
            id=uuid.uuid4(),
            event_type=event_type,
            event_version=DEFAULT_EVENT_VERSION,
            payload=outbox_payload,
            correlation_id=corr_uuid,
            producer_service="gateway",
            status=OutboxStatus.PENDING.value,
            retry_count=0,
            created_at=now,
        )
        session.add(outbox_event)

        # 5. On FALSE_POSITIVE, also emit compensating risk_profile.recalculate event (FR-COMP-001)
        if target_status == AlertStatus.FALSE_POSITIVE:
            comp_payload = {
                "user_id": str(updated_row.user_id),
                "alert_id": str(alert_id),
                "correlation_id": str(corr_uuid),
                "reason": "false_positive_resolution",
                "resolved_at": now.isoformat(),
            }
            comp_event = OutboxEvent(
                id=uuid.uuid4(),
                event_type=EVENT_RISK_PROFILE_RECALCULATE,
                event_version=DEFAULT_EVENT_VERSION,
                payload=comp_payload,
                correlation_id=corr_uuid,
                producer_service="gateway",
                status=OutboxStatus.PENDING.value,
                retry_count=0,
                created_at=now,
            )
            session.add(comp_event)

        # Commit all mutations atomically in one DB transaction
        await session.commit()

        logger.info(
            f"Alert {alert_id} resolved as {target_status.value}",
            extra={
                "alert_id": str(alert_id),
                "status": target_status.value,
                "actor": actor,
                "correlation_id": str(corr_uuid),
            },
        )

        return AlertResolutionResponse(
            alert_id=alert_id,
            status=target_status,
            resolved_by=actor,
            resolved_at=now,
            resolution_reason=resolution_reason,
            correlation_id=str(corr_uuid),
        )
