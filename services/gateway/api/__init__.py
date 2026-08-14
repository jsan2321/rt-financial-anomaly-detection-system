"""
Gateway API routing package.
"""

from fastapi import APIRouter

from .alerts import router as alerts_router
from .health import router as health_router
from .transactions import router as transactions_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(transactions_router)
api_v1_router.include_router(alerts_router)

__all__ = ["api_v1_router", "health_router", "alerts_router", "transactions_router"]
