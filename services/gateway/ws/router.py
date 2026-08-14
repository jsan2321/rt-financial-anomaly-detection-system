"""
WebSocket route handlers for Real-Time Alert notifications.
"""

import json
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from shared.errors.exceptions import AuthenticationError
from shared.logging.json_logger import get_json_logger

from ..auth.jwt import verify_jwt_token
from ..config import settings
from .manager import WebSocketConnectionManager, ws_manager

logger = get_json_logger(__name__)

router = APIRouter(tags=["WebSockets"])

# Custom WebSocket close code for unauthenticated connection attempts
WS_CLOSE_UNAUTHENTICATED = 4401


@router.websocket("/ws/alerts")
async def websocket_alerts_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None, description="JWT access token for authentication"),
) -> None:
    """
    Real-time WebSocket feed for alert lifecycle and escalation events.
    Requires a valid JWT token passed as a query parameter or subprotocol.
    Unauthenticated connections are rejected with close code 4401.
    """
    # Check for token in query parameter or Sec-WebSocket-Protocol header
    auth_token = token
    if not auth_token:
        protocols = websocket.headers.get("sec-websocket-protocol", "").split(",")
        for proto in protocols:
            proto_clean = proto.strip()
            if proto_clean.startswith("Bearer "):
                auth_token = proto_clean.split("Bearer ")[1].strip()
                break
            elif proto_clean and proto_clean != "jwt":
                auth_token = proto_clean
                break

    if not auth_token:
        logger.warning("WebSocket handshake rejected: missing authentication token")
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED, reason="Unauthorized: Missing token")
        return

    try:
        claims = verify_jwt_token(
            token=auth_token,
            secret_key=settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
    except AuthenticationError as err:
        logger.warning(
            f"WebSocket handshake rejected: invalid token ({err.message})",
            extra={"error": str(err)},
        )
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED, reason="Unauthorized: Invalid token")
        return

    client_id = str(claims.get("sub", "analyst_client"))
    await ws_manager.connect(websocket=websocket, client_id=client_id, user_info=claims)

    try:
        while True:
            # Client channel is read-only for business actions; handles heartbeats and ping/pong
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if isinstance(msg, dict) and msg.get("type") == "pong":
                    await ws_manager.record_pong(websocket)
                elif data.strip().lower() == "pong":
                    await ws_manager.record_pong(websocket)
            except Exception:
                if data.strip().lower() == "pong":
                    await ws_manager.record_pong(websocket)
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as err:
        logger.debug(f"WebSocket client connection encountered error: {err}")
        await ws_manager.disconnect(websocket)
