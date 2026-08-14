"""
FastAPI route handlers for Alert endpoints.
"""

from datetime import datetime
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from shared.context.correlation import get_correlation_id
from shared.db.session import get_db_session
from shared.models.enums import AlertSeverity, AlertStatus

from ..schemas.alerts import (
    AlertDetailResponse,
    AlertListResponse,
    AlertResolutionRequest,
    AlertResolutionResponse,
)
from ..services.alert_actions import AlertActionService

router = APIRouter(prefix="/alerts", tags=["Alerts"])


def get_alert_service() -> AlertActionService:
    """Dependency injector for AlertActionService."""
    return AlertActionService()


@router.get(
    "",
    response_model=AlertListResponse,
    status_code=status.HTTP_200_OK,
    summary="List and filter alerts",
)
async def list_alerts(
    status: Optional[AlertStatus] = Query(default=None, description="Filter by alert status"),
    severity: Optional[AlertSeverity] = Query(default=None, description="Filter by alert severity"),
    from_time: Optional[datetime] = Query(default=None, alias="from", description="Created at start filter"),
    to_time: Optional[datetime] = Query(default=None, alias="to", description="Created at end filter"),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=50, ge=1, le=500, description="Items per page"),
    session: AsyncSession = Depends(get_db_session),
    service: AlertActionService = Depends(get_alert_service),
) -> AlertListResponse:
    """
    Retrieves a paginated list of alerts matching optional query filters.
    """
    return await service.get_alerts(
        session=session,
        status=status,
        severity=severity,
        from_time=from_time,
        to_time=to_time,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{alert_id}",
    response_model=AlertDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get alert detail",
)
async def get_alert_detail(
    alert_id: uuid.UUID = Path(..., description="Unique alert identifier"),
    session: AsyncSession = Depends(get_db_session),
    service: AlertActionService = Depends(get_alert_service),
) -> AlertDetailResponse:
    """
    Retrieves full explanation context, feature vector scores, rule matches, and lifecycle history.
    """
    return await service.get_alert_by_id(session=session, alert_id=alert_id)


@router.post(
    "/{alert_id}/approve",
    response_model=AlertResolutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve alert as legitimate",
)
async def approve_alert(
    alert_id: uuid.UUID = Path(..., description="Unique alert identifier"),
    body: Optional[AlertResolutionRequest] = None,
    x_actor: Optional[str] = Header(default="analyst_system", alias="X-Actor"),
    session: AsyncSession = Depends(get_db_session),
    service: AlertActionService = Depends(get_alert_service),
) -> AlertResolutionResponse:
    """
    Resolves an alert as APPROVED (legitimate activity).
    Transitions state, writes audit log, and emits alert.approved outbox event.
    """
    correlation_id = get_correlation_id()
    reason = body.resolution_reason if body else None
    return await service.resolve_alert(
        session=session,
        alert_id=alert_id,
        target_status=AlertStatus.APPROVED,
        actor=x_actor or "analyst_system",
        correlation_id=correlation_id,
        resolution_reason=reason,
    )


@router.post(
    "/{alert_id}/block",
    response_model=AlertResolutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Block alert as confirmed fraud",
)
async def block_alert(
    alert_id: uuid.UUID = Path(..., description="Unique alert identifier"),
    body: Optional[AlertResolutionRequest] = None,
    x_actor: Optional[str] = Header(default="analyst_system", alias="X-Actor"),
    session: AsyncSession = Depends(get_db_session),
    service: AlertActionService = Depends(get_alert_service),
) -> AlertResolutionResponse:
    """
    Resolves an alert as BLOCKED (confirmed fraudulent activity).
    Transitions state, writes audit log, and emits alert.blocked outbox event.
    """
    correlation_id = get_correlation_id()
    reason = body.resolution_reason if body else None
    return await service.resolve_alert(
        session=session,
        alert_id=alert_id,
        target_status=AlertStatus.BLOCKED,
        actor=x_actor or "analyst_system",
        correlation_id=correlation_id,
        resolution_reason=reason,
    )


@router.post(
    "/{alert_id}/false-positive",
    response_model=AlertResolutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark alert as false positive",
)
async def mark_alert_false_positive(
    alert_id: uuid.UUID = Path(..., description="Unique alert identifier"),
    body: Optional[AlertResolutionRequest] = None,
    x_actor: Optional[str] = Header(default="analyst_system", alias="X-Actor"),
    session: AsyncSession = Depends(get_db_session),
    service: AlertActionService = Depends(get_alert_service),
) -> AlertResolutionResponse:
    """
    Resolves an alert as FALSE_POSITIVE.
    Transitions state, writes audit log, and emits alert.false_positive + risk_profile.recalculate outbox events.
    """
    correlation_id = get_correlation_id()
    reason = body.resolution_reason if body else None
    return await service.resolve_alert(
        session=session,
        alert_id=alert_id,
        target_status=AlertStatus.FALSE_POSITIVE,
        actor=x_actor or "analyst_system",
        correlation_id=correlation_id,
        resolution_reason=reason,
    )
