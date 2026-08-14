"""
Structured JSON Logger implementation for RT-FADS services.
"""

from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any, Dict, Optional

from shared.context.correlation import get_correlation_id


class JSONFormatter(logging.Formatter):
    """
    Format Python logging records into structured JSON lines.
    Automatically injects correlation_id, service name, and execution metadata.
    """

    def __init__(self, service_name: str = "rt-fads"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", self.service_name),
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", get_correlation_id()),
        }

        # Inject domain identifiers if present in extra parameters
        for key in ("transaction_id", "alert_id", "event_id", "user_id"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = str(val)

        # Include exception traceback if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Include extra payload dictionaries if attached
        extra_data = getattr(record, "extra_data", None)
        if isinstance(extra_data, dict):
            log_entry["data"] = extra_data

        return json.dumps(log_entry, default=str)


def setup_logging(
    service_name: str = "rt-fads",
    log_level: str = "INFO",
    level: Optional[str] = None,
) -> None:
    """Configure root and application loggers to emit JSON to stdout."""
    effective_level = level if level is not None else log_level
    numeric_level = getattr(logging, effective_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear existing handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(JSONFormatter(service_name=service_name))
    root_logger.addHandler(stream_handler)

    # Silence overly verbose external loggers
    logging.getLogger("uvicorn.access").handlers = [stream_handler]
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a logger instance configured for structured output."""
    return logging.getLogger(name)


# Aliases for explicit semantic naming
setup_json_logging = setup_logging
get_json_logger = get_logger
