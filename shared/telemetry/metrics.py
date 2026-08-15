"""
Thread-safe Prometheus-compatible metrics registry and metric instruments for RT-FADS.
"""

from collections import defaultdict
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import OutboxEvent
from shared.models.enums import OutboxStatus

DEFAULT_HISTOGRAM_BUCKETS: Tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


def _format_labels(labels: Dict[str, str]) -> str:
    """Formats label dictionary to Prometheus standard key=\"value\" string."""
    if not labels:
        return ""
    pairs = [f'{k}="{v}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(pairs) + "}"


class BaseMetric:
    """Base metric class."""

    def __init__(self, name: str, description: str, label_names: Sequence[str] = ()):
        self.name = name
        self.description = description
        self.label_names = tuple(label_names)
        self._lock = threading.Lock()

    def _validate_labels(self, labels: Dict[str, Any]) -> Dict[str, str]:
        normalized = {k: str(v) for k, v in labels.items()}
        for key in self.label_names:
            if key not in normalized:
                normalized[key] = "unknown"
        return normalized

    def collect(self) -> List[str]:
        """Generate Prometheus exposition text lines."""
        raise NotImplementedError


class Counter(BaseMetric):
    """Monotonically increasing cumulative metric."""

    def __init__(self, name: str, description: str, label_names: Sequence[str] = ()):
        super().__init__(name, description, label_names)
        self._values: Dict[Tuple[Tuple[str, str], ...], float] = defaultdict(float)

    def inc(self, value: float = 1.0, **labels: Any) -> None:
        if value < 0:
            raise ValueError("Counter increments must be non-negative")
        norm_labels = self._validate_labels(labels)
        key = tuple(sorted(norm_labels.items()))
        with self._lock:
            self._values[key] += value

    def get(self, **labels: Any) -> float:
        norm_labels = self._validate_labels(labels)
        key = tuple(sorted(norm_labels.items()))
        with self._lock:
            return self._values.get(key, 0.0)

    def collect(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            items = sorted(self._values.items(), key=lambda x: x[0])
            if not items and not self.label_names:
                lines.append(f"{self.name} 0.0")
            else:
                for label_tuple, val in items:
                    label_dict = dict(label_tuple)
                    label_str = _format_labels(label_dict)
                    lines.append(f"{self.name}{label_str} {val}")
        return lines


class Gauge(BaseMetric):
    """Metric that can arbitrarily increase or decrease."""

    def __init__(self, name: str, description: str, label_names: Sequence[str] = ()):
        super().__init__(name, description, label_names)
        self._values: Dict[Tuple[Tuple[str, str], ...], float] = defaultdict(float)

    def set(self, value: float, **labels: Any) -> None:
        norm_labels = self._validate_labels(labels)
        key = tuple(sorted(norm_labels.items()))
        with self._lock:
            self._values[key] = float(value)

    def inc(self, value: float = 1.0, **labels: Any) -> None:
        norm_labels = self._validate_labels(labels)
        key = tuple(sorted(norm_labels.items()))
        with self._lock:
            self._values[key] += float(value)

    def dec(self, value: float = 1.0, **labels: Any) -> None:
        norm_labels = self._validate_labels(labels)
        key = tuple(sorted(norm_labels.items()))
        with self._lock:
            self._values[key] -= float(value)

    def get(self, **labels: Any) -> float:
        norm_labels = self._validate_labels(labels)
        key = tuple(sorted(norm_labels.items()))
        with self._lock:
            return self._values.get(key, 0.0)

    def collect(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} gauge",
        ]
        with self._lock:
            items = sorted(self._values.items(), key=lambda x: x[0])
            if not items and not self.label_names:
                lines.append(f"{self.name} 0.0")
            else:
                for label_tuple, val in items:
                    label_dict = dict(label_tuple)
                    label_str = _format_labels(label_dict)
                    lines.append(f"{self.name}{label_str} {val}")
        return lines


class Histogram(BaseMetric):
    """Samples observations into configurable cumulative buckets."""

    def __init__(
        self,
        name: str,
        description: str,
        label_names: Sequence[str] = (),
        buckets: Sequence[float] = DEFAULT_HISTOGRAM_BUCKETS,
    ):
        super().__init__(name, description, label_names)
        # Ensure buckets are sorted ascending and contain inf
        raw_buckets = sorted(set(buckets))
        if math.inf not in raw_buckets:
            raw_buckets.append(math.inf)
        self.buckets = tuple(raw_buckets)

        self._counts: Dict[Tuple[Tuple[str, str], ...], int] = defaultdict(int)
        self._sums: Dict[Tuple[Tuple[str, str], ...], float] = defaultdict(float)
        self._bucket_counts: Dict[Tuple[Tuple[str, str], ...], Dict[float, int]] = defaultdict(
            lambda: {b: 0 for b in self.buckets}
        )

    def observe(self, amount: float, **labels: Any) -> None:
        norm_labels = self._validate_labels(labels)
        key = tuple(sorted(norm_labels.items()))
        with self._lock:
            self._counts[key] += 1
            self._sums[key] += float(amount)
            bucket_map = self._bucket_counts[key]
            for b in self.buckets:
                if amount <= b:
                    bucket_map[b] += 1

    def time(self, **labels: Any) -> "_HistogramTimer":
        """Context manager to measure execution latency."""
        return _HistogramTimer(self, labels)

    def collect(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} histogram",
        ]
        with self._lock:
            keys = sorted(self._counts.keys(), key=lambda x: x)
            for key in keys:
                label_dict = dict(key)
                count = self._counts[key]
                sum_val = self._sums[key]
                bucket_map = self._bucket_counts[key]

                for b in self.buckets:
                    le_str = "+Inf" if math.isinf(b) else str(b)
                    b_labels = dict(label_dict)
                    b_labels["le"] = le_str
                    lines.append(f"{self.name}_bucket{_format_labels(b_labels)} {bucket_map[b]}")

                lines.append(f"{self.name}_count{_format_labels(label_dict)} {count}")
                lines.append(f"{self.name}_sum{_format_labels(label_dict)} {sum_val}")
        return lines


class _HistogramTimer:
    """Context manager returned by Histogram.time()."""

    def __init__(self, histogram: Histogram, labels: Dict[str, Any]):
        self.histogram = histogram
        self.labels = labels
        self.start_time: float = 0.0

    def __enter__(self) -> "_HistogramTimer":
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        elapsed = time.perf_counter() - self.start_time
        self.histogram.observe(elapsed, **self.labels)


class MetricsRegistry:
    """Singleton registry holding all active system metrics."""

    def __init__(self) -> None:
        self._metrics: Dict[str, BaseMetric] = {}
        self._lock = threading.Lock()

    def register(self, metric: BaseMetric) -> BaseMetric:
        with self._lock:
            if metric.name in self._metrics:
                return self._metrics[metric.name]
            self._metrics[metric.name] = metric
            return metric

    def get_metric(self, name: str) -> Optional[BaseMetric]:
        with self._lock:
            return self._metrics.get(name)

    def generate_prometheus_text(self) -> str:
        """Returns standard Prometheus formatted metrics exposition text."""
        output_blocks: List[str] = []
        with self._lock:
            sorted_metrics = sorted(self._metrics.values(), key=lambda m: m.name)
            for metric in sorted_metrics:
                block = metric.collect()
                if block:
                    output_blocks.append("\n".join(block))
        return "\n\n".join(output_blocks) + "\n"


# Global singleton registry
_GLOBAL_REGISTRY = MetricsRegistry()


def get_metrics_registry() -> MetricsRegistry:
    """Returns the global MetricsRegistry."""
    return _GLOBAL_REGISTRY


# ==============================================================================
# Master RT-FADS Metrics Catalog
# ==============================================================================

# Ingestion & Transactions
transactions_received_total = _GLOBAL_REGISTRY.register(
    Counter(
        "transactions_received_total",
        "Total transactions received by Gateway ingestion endpoint",
        ["status"],
    )
)

transactions_rejected_total = _GLOBAL_REGISTRY.register(
    Counter(
        "transactions_rejected_total",
        "Total transactions rejected by Gateway before persistence",
        ["reason"],
    )
)

transactions_processed_total = _GLOBAL_REGISTRY.register(
    Counter(
        "transactions_processed_total",
        "Total transactions processed through detection pipeline",
        ["status"],
    )
)

processing_failures_total = _GLOBAL_REGISTRY.register(
    Counter(
        "processing_failures_total",
        "Total unhandled transaction processing failures",
        ["stage"],
    )
)

# Alerts & Escalations
alerts_created_total = _GLOBAL_REGISTRY.register(
    Counter(
        "alerts_created_total",
        "Total anomaly alerts generated by severity",
        ["severity"],
    )
)

escalations_total = _GLOBAL_REGISTRY.register(
    Counter(
        "escalations_total",
        "Total alerts escalated through time-driven scheduler",
        ["level"],
    )
)

# Performance & Latency
processing_latency_seconds = _GLOBAL_REGISTRY.register(
    Histogram(
        "processing_latency_seconds",
        "Processing latency in seconds across pipeline stages",
        ["stage"],
    )
)

# Stream & Outbox Backlogs (NFR-OBS-005)
stream_backlog_length = _GLOBAL_REGISTRY.register(
    Gauge(
        "stream_backlog_length",
        "Unprocessed message lag in Redis Streams",
        ["stream"],
    )
)

outbox_backlog_length = _GLOBAL_REGISTRY.register(
    Gauge(
        "outbox_backlog_length",
        "Count of pending events in database Transactional Outbox",
        ["service"],
    )
)

outbox_dead_lettered_total = _GLOBAL_REGISTRY.register(
    Counter(
        "outbox_dead_lettered_total",
        "Total events escalated to Dead Letter table / stream",
        ["stream"],
    )
)

outbox_events_published_total = _GLOBAL_REGISTRY.register(
    Counter(
        "outbox_events_published_total",
        "Total outbox events published to Redis Streams",
        ["event_type"],
    )
)

# WebSocket Surveillance
websocket_connections_active = _GLOBAL_REGISTRY.register(
    Gauge(
        "websocket_connections_active",
        "Number of currently active analyst WebSocket connections",
    )
)


# ==============================================================================
# Backlog Sampling Helpers
# ==============================================================================

async def sample_stream_backlog(
    redis_client: aioredis.Redis,
    stream_name: str,
    group_name: str,
) -> int:
    """
    Computes stream backlog length from Redis consumer group information.
    Uses group lag (Redis 7+) or pending count summary.
    """
    try:
        groups = await redis_client.xinfo_groups(stream_name)
        for group in groups:
            name = group.get("name")
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            if name == group_name:
                lag = group.get("lag")
                if lag is not None and lag >= 0:
                    stream_backlog_length.set(lag, stream=stream_name)
                    return int(lag)
                pending = group.get("pending", 0)
                stream_backlog_length.set(pending, stream=stream_name)
                return int(pending)
    except Exception:
        pass
    return 0


async def sample_outbox_backlog(
    session: AsyncSession,
    service: str = "all",
) -> int:
    """
    Queries count of PENDING outbox events in PostgreSQL and updates gauge.
    """
    try:
        stmt = select(func.count(OutboxEvent.id)).where(
            OutboxEvent.status == OutboxStatus.PENDING.value
        )
        result = await session.execute(stmt)
        count = result.scalar_one() or 0
        outbox_backlog_length.set(count, service=service)
        return int(count)
    except Exception:
        return 0
