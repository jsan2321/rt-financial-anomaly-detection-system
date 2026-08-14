"""
RT-FADS Shared Telemetry Package.
Provides OpenTelemetry distributed tracing, context propagation, and Prometheus metrics.
"""

from .metrics import (
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
from .tracer import (
    extract_trace_context,
    get_tracer,
    init_tracer,
    inject_trace_context,
    shutdown_tracer,
    trace_span,
    traced,
)

__all__ = [
    # Tracing
    "init_tracer",
    "get_tracer",
    "shutdown_tracer",
    "trace_span",
    "traced",
    "inject_trace_context",
    "extract_trace_context",
    # Metrics
    "Counter",
    "Gauge",
    "Histogram",
    "MetricsRegistry",
    "get_metrics_registry",
    # Metric Instances
    "transactions_received_total",
    "transactions_rejected_total",
    "transactions_processed_total",
    "processing_failures_total",
    "alerts_created_total",
    "escalations_total",
    "processing_latency_seconds",
    "stream_backlog_length",
    "outbox_backlog_length",
    "outbox_dead_lettered_total",
    "outbox_events_published_total",
    "websocket_connections_active",
    # Helpers
    "sample_stream_backlog",
    "sample_outbox_backlog",
]
