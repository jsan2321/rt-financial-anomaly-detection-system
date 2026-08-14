"""
Main process entry point for Outbox Publisher worker.
Handles connection lifecycle, signal registration, and graceful shutdown.
"""

import asyncio
import signal
import sys
from typing import Optional

import redis.asyncio as aioredis

from shared.db.session import DatabaseSessionManager, ping_database
from shared.logging.json_logger import get_json_logger, setup_json_logging

from .config import settings
from .publisher import OutboxPublisher

logger = get_json_logger(__name__)


async def main(shutdown_event: Optional[asyncio.Event] = None) -> None:
    """Initializes dependencies and runs the publisher worker loop."""
    setup_json_logging(level=settings.LOG_LEVEL, service_name=settings.APP_NAME)
    logger.info("Initializing Outbox Publisher service", extra={"environment": settings.ENVIRONMENT})

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
        database_url=settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
    )

    # Verify DB connectivity
    await ping_database(db_manager)

    # 2. Initialize Async Redis Client
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )

    # 3. Instantiate OutboxPublisher and run loop
    publisher = OutboxPublisher(settings=settings)

    try:
        await publisher.run_loop(
            db_manager=db_manager,
            redis_client=redis_client,
            shutdown_event=shutdown_event,
        )
    finally:
        logger.info("Closing Outbox Publisher dependencies")
        await redis_client.aclose()
        await db_manager.close()
        logger.info("Outbox Publisher shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, exiting.")
        sys.exit(0)
