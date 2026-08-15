"""
OpenTelemetry distributed tracing configuration, context propagation, and span helpers.
"""

from contextlib import contextmanager
import functools
import inspect
import logging
import os
import sys
from typing import Any, Callable, Dict, Iterator, Optional, TypeVar

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from shared.context.correlation import get_correlation_id

logger = logging.getLogger(__name__)

_GLOBAL_PROVIDER: Optional[TracerProvider] = None
_PROPAGATOR = TraceContextTextMapPropagator()
F = TypeVar("F", bound=Callable[..., Any])


def init_tracer(
    service_name: str = "rt-fads-service",
    otlp_endpoint: Optional[str] = None,
    enabled: bool = True,
    service_version: str = "1.0.0",
    environment: Optional[str] = None,
) -> trace.Tracer:
    """
    Initializes the OpenTelemetry TracerProvider with OTLP exporter and BatchSpanProcessor.
    Safe to call multiple times; returns the service tracer.
    """
    global _GLOBAL_PROVIDER

    if not enabled:
        # If disabled, configure NoOp tracer
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        _GLOBAL_PROVIDER = provider
        return trace.get_tracer(service_name)

    env = environment or os.getenv("ENVIRONMENT", "development")
    endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

    resource = Resource.create(
        attributes={
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment": env,
        }
    )

    provider = TracerProvider(resource=resource)

    # In unit tests, avoid background exporter network attempts to unreachable collector
    is_pytest = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
    if not is_pytest or os.getenv("FORCE_OTEL_EXPORT", "").lower() == "true":
        try:
            otlp_exporter = OTLPSpanExporter(
                endpoint=endpoint,
                insecure=True,
            )
            span_processor = BatchSpanProcessor(
                otlp_exporter,
                max_queue_size=2048,
                schedule_delay_millis=500,
                max_export_batch_size=512,
                export_timeout_millis=3000,
            )
            provider.add_span_processor(span_processor)
        except Exception as exc:
            logger.warning(
                f"Failed to initialize OTLP Span Exporter targeting {endpoint}: {exc}. "
                "Continuing with in-memory TracerProvider without remote export."
            )

    trace.set_tracer_provider(provider)
    _GLOBAL_PROVIDER = provider
    logger.info(
        f"OpenTelemetry tracer initialized for {service_name}",
        extra={"service": service_name, "otlp_endpoint": endpoint, "environment": env},
    )
    return trace.get_tracer(service_name)


def get_tracer(service_name: str = "rt-fads") -> trace.Tracer:
    """Returns a tracer instance for the specified service name."""
    return trace.get_tracer(service_name)


def shutdown_tracer() -> None:
    """Flushes remaining spans and shuts down the active TracerProvider."""
    global _GLOBAL_PROVIDER
    if _GLOBAL_PROVIDER is not None:
        try:
            _GLOBAL_PROVIDER.shutdown()
        except Exception as exc:
            logger.debug(f"Error during TracerProvider shutdown: {exc}")
        _GLOBAL_PROVIDER = None


def inject_trace_context(carrier: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Injects the active span context (W3C traceparent and tracestate) into a dictionary carrier.
    Used when publishing to Redis Streams or making HTTP requests.
    """
    if carrier is None:
        carrier = {}
    _PROPAGATOR.inject(carrier)
    return carrier


def extract_trace_context(carrier: Dict[str, Any]) -> Any:
    """
    Extracts W3C trace context from a dictionary carrier (e.g. from an EventEnvelope or Redis message).
    Returns an OpenTelemetry Context.
    """
    # Normalize string keys and values for propagator
    normalized_carrier = {
        str(k).lower(): str(v)
        for k, v in carrier.items()
        if v is not None and isinstance(v, (str, int, float, bool))
    }
    return _PROPAGATOR.extract(carrier=normalized_carrier)


@contextmanager
def trace_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    tracer_name: str = "rt-fads",
    parent_context: Optional[Any] = None,
) -> Iterator[trace.Span]:
    """
    Context manager to create a tracing span with automatic correlation_id injection
    and exception recording.
    """
    tracer = get_tracer(tracer_name)
    attrs = dict(attributes or {})

    # Auto-inject correlation_id if not explicitly provided
    if "correlation_id" not in attrs:
        attrs["correlation_id"] = get_correlation_id()

    with tracer.start_as_current_span(name, context=parent_context, attributes=attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def traced(
    name: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
    tracer_name: str = "rt-fads",
) -> Callable[[F], F]:
    """
    Decorator for synchronous or asynchronous functions to wrap execution in a trace span.
    """
    def decorator(func: F) -> F:
        span_name = name or f"{func.__module__}.{func.__qualname__}"

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with trace_span(span_name, attributes=attributes, tracer_name=tracer_name):
                    return await func(*args, **kwargs)
            return async_wrapper  # type: ignore[return-value]
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with trace_span(span_name, attributes=attributes, tracer_name=tracer_name):
                    return func(*args, **kwargs)
            return sync_wrapper  # type: ignore[return-value]

    return decorator
