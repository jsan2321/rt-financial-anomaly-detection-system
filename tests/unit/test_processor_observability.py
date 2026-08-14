"""
Unit tests for Processor observability endpoints, readiness checks, and telemetry instrumentation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from services.processor.main import create_processor_metrics_app
from shared.telemetry import (
    alerts_created_total,
    escalations_total,
    transactions_processed_total,
)


@pytest.fixture
def metrics_client():
    mock_db = MagicMock()
    mock_redis = AsyncMock()
    mock_ml = MagicMock()

    app = create_processor_metrics_app(
        db_manager=mock_db,
        redis_client=mock_redis,
        ml_scorer=mock_ml,
    )
    return TestClient(app)


def test_processor_healthz(metrics_client):
    response = metrics_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_processor_readyz_healthy(metrics_client):
    with patch("services.processor.main.ping_database", new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = True
        response = metrics_client.get("/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["dependencies"]["database"] == "connected"
        assert data["dependencies"]["redis"] == "connected"
        assert data["dependencies"]["model_loaded"] == "true"
        assert data["dependencies"]["telemetry"] == "initialized"


def test_processor_readyz_unhealthy_when_model_missing():
    mock_db = MagicMock()
    mock_redis = AsyncMock()

    app = create_processor_metrics_app(
        db_manager=mock_db,
        redis_client=mock_redis,
        ml_scorer=None,  # Model failed to load (FR-ML-004)
    )
    client = TestClient(app)

    with patch("services.processor.main.ping_database", new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = True
        response = client.get("/readyz")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["dependencies"]["model_loaded"] == "false"


def test_processor_metrics_endpoint(metrics_client):
    alerts_created_total.inc(2, severity="CRITICAL")
    escalations_total.inc(1, level="slack")
    transactions_processed_total.inc(10, status="completed")

    response = metrics_client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    content = response.text
    assert "alerts_created_total" in content
    assert "escalations_total" in content
    assert "transactions_processed_total" in content
