"""
Health check and Prometheus metrics endpoints for Gateway service.
Exposes /healthz (liveness), /readyz (readiness per NFR-OBS-006), and /metrics (NFR-OBS-004).
"""

from fastapi import APIRouter, Request, Response, status

from shared.db.session import get_session_manager, ping_database
from shared.telemetry.metrics import get_metrics_registry

router = APIRouter(tags=["Health & Telemetry"])


@router.get("/healthz", status_code=status.HTTP_200_OK, summary="Liveness probe")
async def healthz():
    """Returns 200 if process is running."""
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe")
async def readyz(request: Request, response: Response):
    """
    Checks connectivity to PostgreSQL and Redis per NFR-OBS-006.
    Returns 200 if ready, or 503 if any critical dependency is unavailable.
    """
    dependencies = {
        "database": "unknown",
        "redis": "unknown",
        "telemetry": "initialized",
    }
    is_healthy = True

    # 1. Check PostgreSQL Database
    try:
        manager = get_session_manager()
        db_healthy = await ping_database(manager)
        if db_healthy:
            dependencies["database"] = "connected"
        else:
            dependencies["database"] = "unavailable"
            is_healthy = False
    except Exception:
        dependencies["database"] = "error"
        is_healthy = False

    # 2. Check Redis Messaging
    try:
        redis_client = getattr(request.app.state, "redis", None)
        if redis_client is not None:
            await redis_client.ping()
            dependencies["redis"] = "connected"
        else:
            dependencies["redis"] = "not_initialized"
    except Exception:
        dependencies["redis"] = "unavailable"
        is_healthy = False

    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "dependencies": dependencies}

    return {"status": "ready", "dependencies": dependencies}


@router.get(
    "/metrics",
    summary="Prometheus metrics endpoint",
    response_class=Response,
)
async def get_metrics():
    """
    Exposes Prometheus-formatted system and service metrics (NFR-OBS-004).
    """
    registry = get_metrics_registry()
    metrics_text = registry.generate_prometheus_text()
    return Response(
        content=metrics_text,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
