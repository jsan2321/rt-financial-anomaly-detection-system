"""
Main entry point for RT-FADS FastAPI Gateway service.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from shared.context.correlation import get_correlation_id
from shared.db.session import get_session_manager
from shared.errors.envelope import create_error_envelope
from shared.errors.exceptions import RTFADSError
from shared.logging.json_logger import get_json_logger, setup_json_logging

from .api import api_v1_router, health_router
from .config import settings
from .middleware.correlation import CorrelationIdMiddleware

logger = get_json_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manages service startup and graceful shutdown."""
    setup_json_logging(level=settings.LOG_LEVEL, service_name=settings.APP_NAME)
    logger.info("Starting RT-FADS Gateway service", extra={"environment": settings.ENVIRONMENT})

    # Initialize async database engine
    db_manager = get_session_manager()
    db_manager.init(
        database_url=settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
    )

    yield

    logger.info("Shutting down RT-FADS Gateway service")
    await db_manager.close()


def create_app() -> FastAPI:
    """Factory creating and configuring the Gateway FastAPI application."""
    app = FastAPI(
        title="RT-FADS Gateway",
        description="Real-Time Financial Anomaly Detection System - Ingestion & Analyst Gateway",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Middleware registration
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception Handlers
    @app.exception_handler(RTFADSError)
    async def rtfads_error_handler(request: Request, exc: RTFADSError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        corr_id = get_correlation_id()
        error_env = create_error_envelope(
            code="VALIDATION_ERROR",
            message="Request payload failed validation schema.",
            correlation_id=corr_id,
            details=jsonable_encoder(exc.errors()),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_env,
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        corr_id = get_correlation_id()
        logger.error(f"Database error during request: {str(exc)}", exc_info=True)
        error_env = create_error_envelope(
            code="SERVICE_UNAVAILABLE",
            message="Backing database storage is currently unavailable.",
            correlation_id=corr_id,
            details={"service": "postgresql"},
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_env,
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        corr_id = get_correlation_id()
        logger.error(f"Unhandled server error: {str(exc)}", exc_info=True)
        error_env = create_error_envelope(
            code="INTERNAL_ERROR",
            message="An unexpected internal server error occurred.",
            correlation_id=corr_id,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_env,
        )

    # Mount routers
    app.include_router(health_router)
    app.include_router(api_v1_router)

    return app


app = create_app()
