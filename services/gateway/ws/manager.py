"""
WebSocket Connection Manager for managing active client sessions, broadcasting
notifications, and enforcing heartbeat ping/pong lifecycles.
Instrumented with Prometheus metrics and OpenTelemetry tracing (NFR-OBS-004).
"""

import asyncio
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional, Union

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from shared.logging.json_logger import get_json_logger
from shared.telemetry import trace_span, websocket_connections_active

logger = get_json_logger(__name__)


class WebSocketConnectionManager:
    """
    Manages active WebSocket connections, handles fan-out broadcasting,
    and monitors heartbeat timeouts to detect half-open sockets.
    """

    def __init__(self) -> None:
        self._active_connections: Dict[WebSocket, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        """Returns the number of currently active WebSocket connections."""
        return len(self._active_connections)

    async def connect(
        self,
        websocket: WebSocket,
        client_id: str,
        user_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Accepts and registers a new WebSocket connection.
        """
        await websocket.accept()
        now = datetime.now(timezone.utc)
        async with self._lock:
            self._active_connections[websocket] = {
                "client_id": client_id,
                "user_info": user_info or {},
                "connected_at": now,
                "last_pong": now,
                "last_ping_sent": None,
            }
            active_total = len(self._active_connections)

        websocket_connections_active.set(active_total)
        logger.info(
            "WebSocket client connected",
            extra={
                "client_id": client_id,
                "active_connections": active_total,
            },
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """
        Removes a WebSocket connection from the active pool.
        """
        async with self._lock:
            client_info = self._active_connections.pop(websocket, None)
            active_total = len(self._active_connections)

        websocket_connections_active.set(active_total)
        if client_info:
            logger.info(
                "WebSocket client disconnected",
                extra={
                    "client_id": client_info.get("client_id"),
                    "active_connections": active_total,
                },
            )

    async def record_pong(self, websocket: WebSocket) -> None:
        """
        Records receipt of a pong frame / message from the client.
        """
        async with self._lock:
            if websocket in self._active_connections:
                self._active_connections[websocket]["last_pong"] = datetime.now(timezone.utc)
                self._active_connections[websocket]["last_ping_sent"] = None

    async def send_personal_message(
        self,
        message: Union[str, Dict[str, Any]],
        websocket: WebSocket,
    ) -> bool:
        """
        Sends a JSON or text payload to a single WebSocket client.
        Returns True if sent successfully, False if connection failed.
        """
        payload = json.dumps(message) if isinstance(message, dict) else message
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_text(payload)
                return True
        except (WebSocketDisconnect, RuntimeError, Exception) as err:
            logger.warning(
                f"Failed to send personal message to WebSocket client: {err}",
                extra={"error": str(err)},
            )
            await self.disconnect(websocket)
        return False

    async def broadcast(self, message: Union[str, Dict[str, Any]]) -> int:
        """
        Broadcasts a message to all active WebSocket connections.
        Prunes any closed or failing connections automatically.
        Returns count of successful deliveries.
        """
        payload = json.dumps(message) if isinstance(message, dict) else message

        async with self._lock:
            connections = list(self._active_connections.keys())

        if not connections:
            return 0

        failed_sockets: List[WebSocket] = []
        delivered_count = 0

        with trace_span("gateway.ws_broadcast", attributes={"client_count": len(connections)}):
            for ws in connections:
                try:
                    if ws.client_state == WebSocketState.CONNECTED:
                        await ws.send_text(payload)
                        delivered_count += 1
                    else:
                        failed_sockets.append(ws)
                except (WebSocketDisconnect, RuntimeError, Exception) as err:
                    logger.debug(
                        f"Error broadcasting to WebSocket client, removing socket: {err}",
                        extra={"error": str(err)},
                    )
                    failed_sockets.append(ws)

            if failed_sockets:
                async with self._lock:
                    for ws in failed_sockets:
                        self._active_connections.pop(ws, None)
                    websocket_connections_active.set(len(self._active_connections))

        return delivered_count

    async def run_heartbeat_loop(
        self,
        shutdown_event: asyncio.Event,
        ping_interval: int = 30,
        ping_timeout: int = 10,
    ) -> None:
        """
        Monitors active connections: sends ping frames every ping_interval seconds,
        and terminates sockets that do not respond within ping_timeout seconds.
        """
        logger.info(
            "Starting WebSocket heartbeat monitor loop",
            extra={
                "ping_interval_seconds": ping_interval,
                "ping_timeout_seconds": ping_timeout,
            },
        )

        while not shutdown_event.is_set():
            try:
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=float(ping_interval))
                    break  # shutdown triggered
                except asyncio.TimeoutError:
                    pass  # interval elapsed, perform heartbeat check

                now = datetime.now(timezone.utc)
                stale_sockets: List[WebSocket] = []

                async with self._lock:
                    active_items = list(self._active_connections.items())

                for ws, info in active_items:
                    last_ping = info.get("last_ping_sent")
                    last_pong = info.get("last_pong", info.get("connected_at"))

                    # If a ping was sent and timeout exceeded with no pong
                    if last_ping is not None:
                        elapsed_since_ping = (now - last_ping).total_seconds()
                        if elapsed_since_ping > ping_timeout:
                            logger.warning(
                                "WebSocket client heartbeat pong timeout, terminating connection",
                                extra={
                                    "client_id": info.get("client_id"),
                                    "elapsed_since_ping": elapsed_since_ping,
                                },
                            )
                            stale_sockets.append(ws)
                            continue

                    # Send ping frame / ping message
                    try:
                        if ws.client_state == WebSocketState.CONNECTED:
                            # Send standard ping payload or frame
                            await ws.send_json({"type": "ping", "timestamp": now.isoformat()})
                            async with self._lock:
                                if ws in self._active_connections:
                                    self._active_connections[ws]["last_ping_sent"] = now
                        else:
                            stale_sockets.append(ws)
                    except Exception as ping_err:
                        logger.debug(f"Failed to send ping to WebSocket: {ping_err}")
                        stale_sockets.append(ws)

                # Close and remove stale sockets
                for ws in stale_sockets:
                    try:
                        if ws.client_state == WebSocketState.CONNECTED:
                            await ws.close(code=1001, reason="Heartbeat timeout")
                    except Exception:
                        pass
                    await self.disconnect(ws)

            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.error(f"Error in WebSocket heartbeat loop: {err}", exc_info=True)
                await asyncio.sleep(1.0)

        logger.info("WebSocket heartbeat monitor loop stopped")

    async def close_all(self, code: int = 1000, reason: str = "Server shutdown") -> None:
        """
        Gracefully closes all currently active WebSocket connections.
        """
        async with self._lock:
            connections = list(self._active_connections.keys())
            self._active_connections.clear()
            websocket_connections_active.set(0)

        for ws in connections:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.close(code=code, reason=reason)
            except Exception:
                pass


# Global singleton instance
ws_manager = WebSocketConnectionManager()
