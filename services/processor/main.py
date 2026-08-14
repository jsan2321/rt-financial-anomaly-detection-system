"""
Main process entry point for RT-FADS Processor worker service.
Initializes dependencies, loads ML model fail-closed, launches stream consumer and
XAUTOCLAIM background tasks, and manages graceful shutdown.
"""

import asyncio
from pathlib import Path
import signal
import sys
from typing import Optional

import redis.asyncio as aioredis

from shared.db.session import DatabaseSessionManager, ping_database
from shared.logging.json_logger import get_json_logger, setup_json_logging

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


async def main(
    proc_settings: Optional[ProcessorSettings] = None,
    shutdown_event: Optional[asyncio.Event] = None,
) -> None:
    """Initializes Processor dependencies and runs consumer worker loops."""
    app_settings = proc_settings or settings
    setup_json_logging(level=app_settings.LOG_LEVEL, service_name=app_settings.APP_NAME)
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

    # 5. Launch consumer loops, autoclaim, and escalation scheduler tasks concurrently
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

    tasks = [
        consumer_task,
        autoclaim_task,
        comp_consumer_task,
        comp_autoclaim_task,
        scheduler_task,
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
        logger.info("Processor service shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Processor service interrupted, exiting.")
        sys.exit(0)
    except MLModelLoadError:
        sys.exit(1)
