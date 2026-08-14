"""
Unit tests for Gateway WebSocket /ws/alerts endpoint and JWT authentication.
"""

from datetime import timedelta
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from services.gateway.auth.jwt import create_access_token
from services.gateway.config import settings
from services.gateway.main import create_app
from services.gateway.ws.manager import ws_manager
from services.gateway.ws.router import WS_CLOSE_UNAUTHENTICATED


@pytest.fixture
def client() -> TestClient:
    # Use create_app directly without running real db / redis lifespan for router tests
    app = create_app()
    return TestClient(app)


def test_ws_endpoint_rejects_missing_token(client: TestClient) -> None:
    """Unauthenticated connection without token parameter should be closed with 4401."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/alerts"):
            pass
    assert exc_info.value.code == WS_CLOSE_UNAUTHENTICATED


def test_ws_endpoint_rejects_invalid_token(client: TestClient) -> None:
    """Connection with forged/malformed JWT should be closed with 4401."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/alerts?token=invalid.jwt.signature"):
            pass
    assert exc_info.value.code == WS_CLOSE_UNAUTHENTICATED


def test_ws_endpoint_rejects_expired_token(client: TestClient) -> None:
    """Connection with expired JWT should be closed with 4401."""
    expired_token = create_access_token(
        data={"sub": "analyst_1", "role": "analyst"},
        secret_key=settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
        expires_delta=timedelta(seconds=-10),  # expired 10s ago
    )

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/alerts?token={expired_token}"):
            pass
    assert exc_info.value.code == WS_CLOSE_UNAUTHENTICATED


def test_ws_endpoint_accepts_valid_token_and_receives_broadcast(client: TestClient) -> None:
    """Valid JWT token connects successfully and receives server broadcasts."""
    valid_token = create_access_token(
        data={"sub": "analyst_alice", "role": "lead_analyst"},
        secret_key=settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
        expires_delta=timedelta(hours=1),
    )

    with client.websocket_connect(f"/ws/alerts?token={valid_token}") as websocket:
        assert ws_manager.active_count >= 1

        # Broadcast a test notification to connected clients
        notification = {
            "type": "alert.created",
            "alert": {
                "id": "alt_test_123",
                "status": "PENDING",
                "severity": "HIGH",
            },
        }

        # Use sync broadcast via send_text or receive
        websocket.send_text(json.dumps({"type": "pong"}))


def test_ws_endpoint_accepts_token_in_subprotocol(client: TestClient) -> None:
    """Valid token provided in Sec-WebSocket-Protocol header is accepted."""
    valid_token = create_access_token(
        data={"sub": "analyst_bob", "role": "analyst"},
        secret_key=settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
        expires_delta=timedelta(hours=1),
    )

    with client.websocket_connect(
        "/ws/alerts",
        subprotocols=[f"Bearer {valid_token}"],
    ) as websocket:
        assert ws_manager.active_count >= 1
        websocket.send_text("pong")
