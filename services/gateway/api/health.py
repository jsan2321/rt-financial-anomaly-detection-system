"""
Health check endpoints for Gateway service.
Exposes /healthz (liveness) and /readyz (readiness).
"""

from fastapi import APIRouter, Response, status

from shared.db.session import get_session_manager, ping_database

router = APIRouter(tags=["Health & Probes"])


@router.get("/healthz", status_code=status.HTTP_200_OK, summary="Liveness probe")
async def healthz():
    """Returns 200 if process is running."""
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe")
async def readyz(response: Response):
    """
    Checks connectivity to PostgreSQL database.
    Returns 200 if healthy, or 503 if unavailable.
    """
    try:
        manager = get_session_manager()
        db_healthy = await ping_database(manager)
        if not db_healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "unhealthy", "database": "unavailable"}
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "database": "error"}

    return {"status": "ready", "database": "connected"}
