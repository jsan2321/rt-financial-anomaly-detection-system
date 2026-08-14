"""
Unit tests for shared.telemetry.metrics Prometheus registry and instruments.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from shared.telemetry.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    alerts_created_total,
    escalations_total,
    get_metrics_registry,
    outbox_backlog_length,
    outbox_dead_lettered_total,
    outbox_events_published_total,
    processing_failures_total,
    processing_latency_seconds,
    sample_outbox_backlog,
    sample_stream_backlog,
    stream_backlog_length,
    transactions_processed_total,
    transactions_received_total,
    transactions_rejected_total,
    websocket_connections_active,
)


def test_counter_inc_and_collect():
    counter = Counter("test_counter_total", "Test counter description", ["status"])
    assert counter.get(status="success") == 0.0

    counter.inc(1.0, status="success")
    counter.inc(2.5, status="success")
    counter.inc(1.0, status="failure")

    assert counter.get(status="success") == 3.5
    assert counter.get(status="failure") == 1.0

    lines = counter.collect()
    text = "\n".join(lines)
    assert "# HELP test_counter_total Test counter description" in text
    assert "# TYPE test_counter_total counter" in text
    assert 'test_counter_total{status="success"} 3.5' in text
    assert 'test_counter_total{status="failure"} 1.0' in text


def test_counter_negative_inc_raises():
    counter = Counter("test_counter", "Description")
    with pytest.raises(ValueError, match="non-negative"):
        counter.inc(-1.0)


def test_gauge_set_inc_dec():
    gauge = Gauge("test_gauge", "Test gauge description", ["service"])
    assert gauge.get(service="gateway") == 0.0

    gauge.set(42.0, service="gateway")
    assert gauge.get(service="gateway") == 42.0

    gauge.inc(5.0, service="gateway")
    assert gauge.get(service="gateway") == 47.0

    gauge.dec(2.0, service="gateway")
    assert gauge.get(service="gateway") == 45.0

    lines = gauge.collect()
    text = "\n".join(lines)
    assert "# TYPE test_gauge gauge" in text
    assert 'test_gauge{service="gateway"} 45.0' in text


def test_histogram_observe_and_timer():
    hist = Histogram("test_duration_seconds", "Test duration", ["stage"], buckets=[0.1, 0.5, 1.0])
    hist.observe(0.05, stage="parse")
    hist.observe(0.3, stage="parse")
    hist.observe(0.8, stage="parse")
    hist.observe(2.0, stage="parse")

    with hist.time(stage="parse"):
        # Small sleep
        pass

    lines = hist.collect()
    text = "\n".join(lines)
    assert "# TYPE test_duration_seconds histogram" in text
    assert 'test_duration_seconds_bucket{le="0.1",stage="parse"}' in text
    assert 'test_duration_seconds_bucket{le="+Inf",stage="parse"}' in text
    assert 'test_duration_seconds_count{stage="parse"}' in text
    assert 'test_duration_seconds_sum{stage="parse"}' in text


def test_global_metrics_registry_generate_text():
    registry = get_metrics_registry()
    transactions_received_total.inc(1, status="accepted")
    alerts_created_total.inc(1, severity="HIGH")
    escalations_total.inc(1, level="email")
    websocket_connections_active.set(5)

    prom_text = registry.generate_prometheus_text()
    assert "transactions_received_total" in prom_text
    assert "alerts_created_total" in prom_text
    assert "escalations_total" in prom_text
    assert "websocket_connections_active" in prom_text


@pytest.mark.asyncio
async def test_sample_stream_backlog():
    mock_redis = AsyncMock()
    mock_redis.xinfo_groups.return_value = [
        {"name": "processor-group", "lag": 7, "pending": 3},
        {"name": "other-group", "lag": 0, "pending": 0},
    ]

    lag = await sample_stream_backlog(
        redis_client=mock_redis,
        stream_name="stream:transactions",
        group_name="processor-group",
    )
    assert lag == 7
    assert stream_backlog_length.get(stream="stream:transactions") == 7.0


@pytest.mark.asyncio
async def test_sample_outbox_backlog():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 14
    mock_session.execute.return_value = mock_result

    count = await sample_outbox_backlog(session=mock_session, service="gateway")
    assert count == 14
    assert outbox_backlog_length.get(service="gateway") == 14.0
