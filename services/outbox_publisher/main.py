"""
Main process entry point for Outbox Publisher worker.
Handles connection lifecycle, signal registration, health/metrics server, and graceful shutdown.
"""

import asyncio
import signal
import sys
from typing import Dict, Optional

from fastapi import FastAPI, Response, status
import redis.asyncio as aioredis
import uvicorn

from shared.db.session import DatabaseSessionManager, ping_database
from shared.logging.json_logger import get_json_logger, setup_json_logging
from shared.telemetry import get_metrics_registry, init_tracer, shutdown_tracer

from .config import OutboxPublisherSettings, settings
from .publisher import OutboxPublisher

logger = get_json_logger(__name__)


def create_outbox_metrics_app(
    db_manager: DatabaseSessionManager,
    redis_client: aioredis.Redis,
) -> FastAPI:
    """Creates a lightweight FastAPI application for Outbox Publisher health and metrics."""
    app = FastAPI(title="RT-FADS Outbox Publisher Probes & Metrics", docs_url=None, redoc_url=None)

    @app.get("/healthz", status_code=status.HTTP_200_OK, summary="Liveness probe")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz", summary="Readiness probe per NFR-OBS-006")
    async def readyz(response: Response):
        dependencies: Dict[str, str] = {
            "database": "unknown",
            "redis": "unknown",
            "telemetry": "initialized",
        }
        is_healthy = True

        # Check DB
        try:
            db_healthy = await ping_database(db_manager)
            dependencies["database"] = "connected" if db_healthy else "unavailable"
            if not db_healthy:
                is_healthy = False
        except Exception:
            dependencies["database"] = "error"
            is_healthy = False

        # Check Redis
        try:
            await redis_client.ping()
            dependencies["redis"] = "connected"
        except Exception:
            dependencies["redis"] = "unavailable"
            is_healthy = False

        if not is_healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "unhealthy", "dependencies": dependencies}

        return {"status": "ready", "dependencies": dependencies}

    @app.get("/metrics", summary="Prometheus metrics", response_class=Response)
    async def get_metrics():
        registry = get_metrics_registry()
        return Response(
            content=registry.generate_prometheus_text(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return app


async def run_metrics_server(
    app: FastAPI,
    host: str,
    port: int,
    shutdown_event: asyncio.Event,
) -> None:
    """Runs the Uvicorn server serving healthz, readyz, and metrics in an async task."""
    config = uvicorn.Config(app=app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config=config)

    serve_task = asyncio.create_task(server.serve())
    try:
        await shutdown_event.wait()
        server.should_exit = True
        await serve_task
    except asyncio.CancelledError:
        server.should_exit = True
        await serve_task


async def main(
    pub_settings: Optional[OutboxPublisherSettings] = None,
    shutdown_event: Optional[asyncio.Event] = None,
) -> None:
    """Initializes dependencies and runs the publisher worker loop and metrics server."""
    app_settings = pub_settings or settings
    setup_json_logging(level=app_settings.LOG_LEVEL, service_name=app_settings.APP_NAME)
    init_tracer(
        service_name=app_settings.APP_NAME,
        otlp_endpoint=app_settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        enabled=app_settings.OTEL_ENABLED,
        environment=app_settings.ENVIRONMENT,
    )
    logger.info("Initializing Outbox Publisher service", extra={"environment": app_settings.ENVIRONMENT})

    if shutdown_event is None:
        shutdown_event = asyncio.Event()

    # Register OS signals for graceful shutdown (on non-Windows or where supported)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except (NotImplementedError, AttributeError):
            # Windows signal handler fallback
            pass

    # 1. Initialize Database Session Manager
    db_manager = DatabaseSessionManager()
    db_manager.init(
        database_url=app_settings.DATABASE_URL,
        pool_size=app_settings.DB_POOL_SIZE,
        max_overflow=app_settings.DB_MAX_OVERFLOW,
    )

    # Verify DB connectivity
    await ping_database(db_manager)

    # 2. Initialize Async Redis Client
    redis_client = aioredis.from_url(
        app_settings.REDIS_URL,
        decode_responses=True,
    )

    # 3. Instantiate OutboxPublisher
    publisher = OutboxPublisher(settings=app_settings)

    # Create Probe & Metrics App (NFR-OBS-004, NFR-OBS-006)
    metrics_app = create_outbox_metrics_app(
        db_manager=db_manager,
        redis_client=redis_client,
    )

    # 4. Launch publisher loop and metrics server tasks
    publisher_task = asyncio.create_task(
        publisher.run_loop(
            db_manager=db_manager,
            redis_client=redis_client,
            shutdown_event=shutdown_event,
        )
    )
    metrics_task = asyncio.create_task(
        run_metrics_server(
            app=metrics_app,
            host=app_settings.OUTBOX_METRICS_HOST,
            port=app_settings.OUTBOX_METRICS_PORT,
            shutdown_event=shutdown_event,
        )
    )

    tasks = [publisher_task, metrics_task]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Closing Outbox Publisher dependencies")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await redis_client.aclose()
        await db_manager.close()
        shutdown_tracer()
        logger.info("Outbox Publisher shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, exiting.")
        sys.exit(0)
