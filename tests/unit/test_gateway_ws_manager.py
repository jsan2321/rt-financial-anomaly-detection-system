"""
Unit tests for WebSocket Connection Manager.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.websockets import WebSocketState

from services.gateway.ws.manager import WebSocketConnectionManager


@pytest.fixture
def manager() -> WebSocketConnectionManager:
    return WebSocketConnectionManager()


@pytest.fixture
def mock_websocket() -> MagicMock:
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    ws.client_state = WebSocketState.CONNECTED
    return ws


@pytest.mark.asyncio
async def test_websocket_manager_connect_and_disconnect(
    manager: WebSocketConnectionManager,
    mock_websocket: MagicMock,
) -> None:
    assert manager.active_count == 0

    await manager.connect(mock_websocket, client_id="user_123", user_info={"role": "analyst"})
    mock_websocket.accept.assert_awaited_once()
    assert manager.active_count == 1

    await manager.disconnect(mock_websocket)
    assert manager.active_count == 0


@pytest.mark.asyncio
async def test_websocket_manager_send_personal_message(
    manager: WebSocketConnectionManager,
    mock_websocket: MagicMock,
) -> None:
    await manager.connect(mock_websocket, client_id="user_123")

    msg = {"type": "test", "data": "hello"}
    success = await manager.send_personal_message(msg, mock_websocket)
    assert success is True
    mock_websocket.send_text.assert_awaited_once_with(json.dumps(msg))


@pytest.mark.asyncio
async def test_websocket_manager_send_personal_message_failure(
    manager: WebSocketConnectionManager,
    mock_websocket: MagicMock,
) -> None:
    await manager.connect(mock_websocket, client_id="user_123")
    mock_websocket.send_text.side_effect = RuntimeError("Socket disconnected")

    success = await manager.send_personal_message("test message", mock_websocket)
    assert success is False
    # Socket should be automatically disconnected
    assert manager.active_count == 0


@pytest.mark.asyncio
async def test_websocket_manager_broadcast_multiple(
    manager: WebSocketConnectionManager,
) -> None:
    ws1 = MagicMock()
    ws1.accept = AsyncMock()
    ws1.send_text = AsyncMock()
    ws1.client_state = WebSocketState.CONNECTED

    ws2 = MagicMock()
    ws2.accept = AsyncMock()
    ws2.send_text = AsyncMock()
    ws2.client_state = WebSocketState.CONNECTED

    await manager.connect(ws1, client_id="analyst_1")
    await manager.connect(ws2, client_id="analyst_2")
    assert manager.active_count == 2

    notification = {"type": "alert.created", "alert": {"id": "alt_1"}}
    delivered = await manager.broadcast(notification)
    assert delivered == 2

    expected_payload = json.dumps(notification)
    ws1.send_text.assert_awaited_once_with(expected_payload)
    ws2.send_text.assert_awaited_once_with(expected_payload)


@pytest.mark.asyncio
async def test_websocket_manager_broadcast_prunes_dead_sockets(
    manager: WebSocketConnectionManager,
) -> None:
    ws1 = MagicMock()
    ws1.accept = AsyncMock()
    ws1.send_text = AsyncMock()
    ws1.client_state = WebSocketState.CONNECTED

    ws2 = MagicMock()
    ws2.accept = AsyncMock()
    ws2.send_text = AsyncMock(side_effect=RuntimeError("Connection reset by peer"))
    ws2.client_state = WebSocketState.CONNECTED

    await manager.connect(ws1, client_id="analyst_1")
    await manager.connect(ws2, client_id="analyst_2")
    assert manager.active_count == 2

    delivered = await manager.broadcast({"type": "ping"})
    assert delivered == 1
    assert manager.active_count == 1


@pytest.mark.asyncio
async def test_websocket_manager_record_pong(
    manager: WebSocketConnectionManager,
    mock_websocket: MagicMock,
) -> None:
    await manager.connect(mock_websocket, client_id="user_123")
    initial_pong = manager._active_connections[mock_websocket]["last_pong"]

    await asyncio.sleep(0.01)
    await manager.record_pong(mock_websocket)

    updated_pong = manager._active_connections[mock_websocket]["last_pong"]
    assert updated_pong > initial_pong


@pytest.mark.asyncio
async def test_websocket_manager_close_all(
    manager: WebSocketConnectionManager,
    mock_websocket: MagicMock,
) -> None:
    await manager.connect(mock_websocket, client_id="user_123")
    assert manager.active_count == 1

    await manager.close_all(code=1000, reason="Server stopping")
    mock_websocket.close.assert_awaited_once_with(code=1000, reason="Server stopping")
    assert manager.active_count == 0


@pytest.mark.asyncio
async def test_websocket_manager_heartbeat_loop_detects_timeout(
    manager: WebSocketConnectionManager,
    mock_websocket: MagicMock,
) -> None:
    await manager.connect(mock_websocket, client_id="stale_client")

    # Set last_ping_sent in the past to trigger timeout
    past_time = datetime.now(timezone.utc) - timedelta(seconds=20)
    manager._active_connections[mock_websocket]["last_ping_sent"] = past_time

    shutdown_event = asyncio.Event()

    # Run heartbeat loop with tiny interval and timeout
    heartbeat_task = asyncio.create_task(
        manager.run_heartbeat_loop(
            shutdown_event=shutdown_event,
            ping_interval=0,  # immediate tick
            ping_timeout=5,
        )
    )

    # Let the loop execute one cycle
    await asyncio.sleep(0.05)
    shutdown_event.set()
    await heartbeat_task

    # Stale connection should be closed and pruned
    mock_websocket.close.assert_awaited_once_with(code=1001, reason="Heartbeat timeout")
    assert manager.active_count == 0
