"""
Unit tests for Gateway observability endpoints and telemetry integration.
"""

from unittest.mock import AsyncMock, patch
import uuid

from fastapi.testclient import TestClient
import pytest

from services.gateway.config import GatewaySettings
from services.gateway.main import create_app
from services.gateway.schemas.transactions import TransactionCreateRequest
from services.gateway.services.ingestion import IngestionService
from shared.telemetry import (
    get_metrics_registry,
    transactions_received_total,
    websocket_connections_active,
)


@pytest.fixture
def client():
    app = create_app()
    # Provide mock app state redis
    app.state.redis = AsyncMock()
    return TestClient(app)


def test_gateway_healthz_endpoint(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_gateway_readyz_healthy(client):
    with patch("services.gateway.api.health.ping_database", new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = True
        client.app.state.redis.ping = AsyncMock(return_value=True)

        response = client.get("/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["dependencies"]["database"] == "connected"
        assert data["dependencies"]["redis"] == "connected"
        assert data["dependencies"]["telemetry"] == "initialized"


def test_gateway_readyz_unhealthy_when_db_down(client):
    with patch("services.gateway.api.health.ping_database", new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = False
        client.app.state.redis.ping = AsyncMock(return_value=True)

        response = client.get("/readyz")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["dependencies"]["database"] == "unavailable"


def test_gateway_metrics_endpoint(client):
    transactions_received_total.inc(5, status="accepted")
    websocket_connections_active.set(3)

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    content = response.text
    assert "transactions_received_total" in content
    assert "websocket_connections_active" in content
