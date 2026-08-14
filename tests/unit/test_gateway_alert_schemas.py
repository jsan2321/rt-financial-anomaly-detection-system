"""
Unit tests for Gateway alert schemas.
"""

from datetime import datetime, timezone
from decimal import Decimal
import uuid
import pytest
from pydantic import ValidationError

from services.gateway.schemas.alerts import (
    AlertDetailResponse,
    AlertListResponse,
    AlertResolutionRequest,
    AlertResolutionResponse,
    AlertSummaryItem,
)
from shared.models.enums import AlertSeverity, AlertStatus


def test_alert_resolution_request_valid():
    req = AlertResolutionRequest(resolution_reason="Customer confirmed by phone")
    assert req.resolution_reason == "Customer confirmed by phone"

    req_none = AlertResolutionRequest()
    assert req_none.resolution_reason is None


def test_alert_resolution_request_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        AlertResolutionRequest(resolution_reason="Reason", invalid_extra="value")


def test_alert_summary_item_serialization():
    alert_id = uuid.uuid4()
    txn_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    item = AlertSummaryItem(
        id=alert_id,
        transaction_id=txn_id,
        user_id=user_id,
        status=AlertStatus.PENDING,
        severity=AlertSeverity.CRITICAL,
        composite_risk_score=Decimal("0.9500"),
        is_demo=False,
        created_at=now,
    )

    data = item.model_dump(mode="json")
    assert data["id"] == str(alert_id)
    assert data["status"] == "PENDING"
    assert data["severity"] == "CRITICAL"
    assert data["composite_risk_score"] == "0.9500"
    assert data["is_demo"] is False


def test_alert_list_response():
    resp = AlertListResponse(
        items=[],
        page=1,
        page_size=50,
        total=0,
    )
    assert resp.page == 1
    assert resp.total == 0
    assert len(resp.items) == 0


def test_alert_detail_response_serialization():
    alert_id = uuid.uuid4()
    txn_id = uuid.uuid4()
    user_id = uuid.uuid4()
    corr_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    detail = AlertDetailResponse(
        id=alert_id,
        transaction_id=txn_id,
        user_id=user_id,
        status=AlertStatus.APPROVED,
        severity=AlertSeverity.HIGH,
        composite_risk_score=Decimal("0.7500"),
        ml_anomaly_score=Decimal("0.6000"),
        rule_matches=[{"rule_name": "High Amount", "severity": "HIGH"}],
        risk_profile_snapshot={"risk_score": "0.2000"},
        is_demo=True,
        resolved_by="analyst_alice",
        resolved_at=now,
        resolution_reason="Legitimate transaction verified",
        escalated_email_at=None,
        escalated_slack_at=None,
        correlation_id=corr_id,
        created_at=now,
    )

    data = detail.model_dump(mode="json")
    assert data["status"] == "APPROVED"
    assert data["resolved_by"] == "analyst_alice"
    assert data["is_demo"] is True
    assert len(data["rule_matches"]) == 1
