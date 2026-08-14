"""
Main process entry point for RT-FADS Processor worker service.
Initializes dependencies, loads ML model fail-closed, launches stream consumer and
XAUTOCLAIM background tasks, serves /healthz, /readyz, /metrics, and manages graceful shutdown.
"""

import asyncio
from pathlib import Path
import signal
import sys
from typing import Any, Dict, Optional

from fastapi import FastAPI, Response, status
import redis.asyncio as aioredis
import uvicorn

from shared.db.session import DatabaseSessionManager, ping_database
from shared.logging.json_logger import get_json_logger, setup_json_logging
from shared.telemetry import get_metrics_registry, init_tracer, shutdown_tracer

from .config import ProcessorSettings, settings
from .consumers.compensation_consumer import CompensationConsumer
from .consumers.transaction_consumer import TransactionConsumer
from .domain.demo_strategy import get_demo_strategy
from .domain.ml_model import MLAnomalyScorer, MLModelLoadError
from .domain.schemas import ScoringWeights
from .scheduler.escalation_scheduler import EscalationScheduler
from .services.compensation_service import RiskCompensationService
from .services.detection_pipeline import DetectionPipeline
from .services.rule_cache import RuleCache

logger = get_json_logger(__name__)


def create_processor_metrics_app(
    db_manager: DatabaseSessionManager,
    redis_client: aioredis.Redis,
    ml_scorer: Optional[MLAnomalyScorer] = None,
) -> FastAPI:
    """Creates a lightweight FastAPI application for Processor health, readiness, and metrics."""
    app = FastAPI(title="RT-FADS Processor Probes & Metrics", docs_url=None, redoc_url=None)

    @app.get("/healthz", status_code=status.HTTP_200_OK, summary="Liveness probe")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz", summary="Readiness probe per NFR-OBS-006")
    async def readyz(response: Response):
        dependencies: Dict[str, str] = {
            "database": "unknown",
            "redis": "unknown",
            "model_loaded": "true" if ml_scorer is not None else "false",
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

        # Check ML model (FR-ML-004)
        if ml_scorer is None:
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

    # Launch server and handle shutdown
    serve_task = asyncio.create_task(server.serve())
    try:
        await shutdown_event.wait()
        server.should_exit = True
        await serve_task
    except asyncio.CancelledError:
        server.should_exit = True
        await serve_task


async def main(
    proc_settings: Optional[ProcessorSettings] = None,
    shutdown_event: Optional[asyncio.Event] = None,
) -> None:
    """Initializes Processor dependencies and runs consumer worker loops."""
    app_settings = proc_settings or settings
    setup_json_logging(level=app_settings.LOG_LEVEL, service_name=app_settings.APP_NAME)
    init_tracer(
        service_name=app_settings.APP_NAME,
        otlp_endpoint=app_settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        enabled=app_settings.OTEL_ENABLED,
        environment=app_settings.ENVIRONMENT,
    )

    logger.info(
        "Initializing RT-FADS Processor service",
        extra={
            "environment": app_settings.ENVIRONMENT,
            "demo_mode": app_settings.DEMO_MODE,
            "stream": app_settings.STREAM_TRANSACTIONS,
            "consumer_group": app_settings.GROUP_TRANSACTIONS,
        },
    )

    if shutdown_event is None:
        shutdown_event = asyncio.Event()

    # Register OS signals for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except (NotImplementedError, AttributeError):
            # Windows fallback
            pass

    # 1. Load ML Model (Fail-Closed)
    logger.info(
        "Loading ML Isolation Forest model artifact",
        extra={
            "model_path": app_settings.MODEL_PATH,
            "metadata_path": app_settings.MODEL_META_PATH,
        },
    )
    try:
        ml_scorer = MLAnomalyScorer.load(
            model_path=app_settings.MODEL_PATH,
            metadata_path=app_settings.MODEL_META_PATH,
        )
        logger.info("ML model and metadata loaded successfully")
    except MLModelLoadError as err:
        logger.critical(
            f"FAIL-CLOSED: Processor cannot start because ML model artifact failed to load: {err.message}",
            extra={"error": str(err), "details": err.details},
            exc_info=True,
        )
        raise

    # 2. Initialize Database Session Manager
    db_manager = DatabaseSessionManager()
    db_manager.init(
        database_url=app_settings.DATABASE_URL,
        pool_size=app_settings.DB_POOL_SIZE,
        max_overflow=app_settings.DB_MAX_OVERFLOW,
    )
    await ping_database(db_manager)

    # 3. Initialize Async Redis Client
    redis_client = aioredis.from_url(
        app_settings.REDIS_URL,
        decode_responses=True,
    )

    # 4. Instantiate Pipeline, Consumers, & Escalation Scheduler
    rule_cache = RuleCache(refresh_ttl_seconds=app_settings.FRAUD_RULE_REFRESH_SECONDS)
    demo_strategy = get_demo_strategy(demo_mode=app_settings.DEMO_MODE)
    scoring_weights = ScoringWeights(
        w_rule=app_settings.W_RULE,
        w_ml=app_settings.W_ML,
        w_profile=app_settings.W_PROFILE,
        alert_threshold=app_settings.ALERT_THRESHOLD,
    )

    pipeline = DetectionPipeline(
        rule_cache=rule_cache,
        ml_detector=ml_scorer,
        demo_strategy=demo_strategy,
        scoring_weights=scoring_weights,
        velocity_window_minutes=app_settings.VELOCITY_WINDOW_MINUTES,
        consumer_group=app_settings.GROUP_TRANSACTIONS,
    )

    consumer = TransactionConsumer(
        pipeline=pipeline,
        settings=app_settings,
    )

    compensation_service = RiskCompensationService()
    compensation_consumer = CompensationConsumer(
        compensation_service=compensation_service,
        settings=app_settings,
    )

    scheduler = EscalationScheduler(
        settings=app_settings,
    )

    # Create Probe & Metrics App (NFR-OBS-004, NFR-OBS-006)
    metrics_app = create_processor_metrics_app(
        db_manager=db_manager,
        redis_client=redis_client,
        ml_scorer=ml_scorer,
    )

    # 5. Launch consumer loops, autoclaim, metrics server, and escalation scheduler tasks concurrently
    consumer_task = asyncio.create_task(
        consumer.run_consumer_loop(
            db_manager=db_manager,
            redis_client=redis_client,
            shutdown_event=shutdown_event,
        )
    )
    autoclaim_task = asyncio.create_task(
        consumer.run_autoclaim_loop(
            db_manager=db_manager,
            redis_client=redis_client,
            shutdown_event=shutdown_event,
        )
    )
    comp_consumer_task = asyncio.create_task(
        compensation_consumer.run_consumer_loop(
            db_manager=db_manager,
            redis_client=redis_client,
            shutdown_event=shutdown_event,
        )
    )
    comp_autoclaim_task = asyncio.create_task(
        compensation_consumer.run_autoclaim_loop(
            db_manager=db_manager,
            redis_client=redis_client,
            shutdown_event=shutdown_event,
        )
    )
    scheduler_task = asyncio.create_task(
        scheduler.run_scheduler_loop(
            db_manager=db_manager,
            shutdown_event=shutdown_event,
        )
    )
    metrics_server_task = asyncio.create_task(
        run_metrics_server(
            app=metrics_app,
            host=app_settings.PROCESSOR_METRICS_HOST,
            port=app_settings.PROCESSOR_METRICS_PORT,
            shutdown_event=shutdown_event,
        )
    )

    tasks = [
        consumer_task,
        autoclaim_task,
        comp_consumer_task,
        comp_autoclaim_task,
        scheduler_task,
        metrics_server_task,
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Closing Processor dependencies")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await redis_client.aclose()
        await db_manager.close()
        shutdown_tracer()
        logger.info("Processor service shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Processor service interrupted, exiting.")
        sys.exit(0)
    except MLModelLoadError:
        sys.exit(1)
