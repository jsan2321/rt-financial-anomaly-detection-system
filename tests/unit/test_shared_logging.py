"""
Unit tests for shared.logging.json_logger.
"""

import json
import logging
from shared.context.correlation import correlation_scope
from shared.logging.json_logger import JSONFormatter, setup_logging, get_logger


def test_json_formatter_standard_fields():
    formatter = JSONFormatter(service_name="test-gateway")
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Processing transaction batch",
        args=(),
        exc_info=None,
    )

    with correlation_scope("cid-log-123"):
        formatted = formatter.format(record)
        data = json.loads(formatted)

        assert data["service"] == "test-gateway"
        assert data["level"] == "INFO"
        assert data["logger"] == "test_logger"
        assert data["message"] == "Processing transaction batch"
        assert data["correlation_id"] == "cid-log-123"
        assert "timestamp" in data


def test_json_formatter_domain_identifiers():
    formatter = JSONFormatter(service_name="test-processor")
    record = logging.LogRecord(
        name="detector",
        level=logging.WARNING,
        pathname=__file__,
        lineno=20,
        msg="High risk score calculated",
        args=(),
        exc_info=None,
    )
    record.transaction_id = "txn_8888"
    record.alert_id = "alt_9999"
    record.user_id = "usr_1111"

    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert data["transaction_id"] == "txn_8888"
    assert data["alert_id"] == "alt_9999"
    assert data["user_id"] == "usr_1111"


def test_json_formatter_exception_and_extra_data():
    formatter = JSONFormatter(service_name="test-logger")
    try:
        raise ValueError("Simulated fault")
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test_err",
        level=logging.ERROR,
        pathname=__file__,
        lineno=45,
        msg="Execution failed",
        args=(),
        exc_info=exc_info,
    )
    record.extra_data = {"retries": 3, "destination": "redis"}

    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert "exception" in data
    assert "ValueError: Simulated fault" in data["exception"]
    assert data["data"] == {"retries": 3, "destination": "redis"}


def test_setup_logging_and_get_logger():
    setup_logging(service_name="test-service", log_level="DEBUG")
    logger = get_logger("unit_test")
    assert logger.name == "unit_test"
