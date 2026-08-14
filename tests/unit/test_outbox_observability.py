"""
Unit tests for Outbox Publisher observability endpoints and metrics.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from services.outbox_publisher.main import create_outbox_metrics_app
from shared.telemetry import (
    outbox_backlog_length,
    outbox_dead_lettered_total,
    outbox_events_published_total,
)


@pytest.fixture
def outbox_metrics_client():
    mock_db = MagicMock()
    mock_redis = AsyncMock()

    app = create_outbox_metrics_app(
        db_manager=mock_db,
        redis_client=mock_redis,
    )
    return TestClient(app)


def test_outbox_healthz(outbox_metrics_client):
    response = outbox_metrics_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_outbox_readyz_healthy(outbox_metrics_client):
    with patch("services.outbox_publisher.main.ping_database", new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = True
        response = outbox_metrics_client.get("/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["dependencies"]["database"] == "connected"
        assert data["dependencies"]["redis"] == "connected"
        assert data["dependencies"]["telemetry"] == "initialized"


def test_outbox_readyz_unhealthy_when_db_down(outbox_metrics_client):
    with patch("services.outbox_publisher.main.ping_database", new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = False
        response = outbox_metrics_client.get("/readyz")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["dependencies"]["database"] == "unavailable"


def test_outbox_metrics_endpoint(outbox_metrics_client):
    outbox_events_published_total.inc(1, event_type="transaction.created")
    outbox_dead_lettered_total.inc(1, stream="stream:transactions")
    outbox_backlog_length.set(12, service="outbox_publisher")

    response = outbox_metrics_client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    content = response.text
    assert "outbox_events_published_total" in content
    assert "outbox_dead_lettered_total" in content
    assert "outbox_backlog_length" in content
