"""
Unit tests for shared.telemetry.tracer OpenTelemetry integration.
"""

from opentelemetry.trace import NonRecordingSpan, Span
import pytest

from shared.context.correlation import correlation_scope, get_correlation_id
from shared.telemetry.tracer import (
    extract_trace_context,
    get_tracer,
    init_tracer,
    inject_trace_context,
    shutdown_tracer,
    trace_span,
    traced,
)


def test_init_and_get_tracer():
    tracer = init_tracer(service_name="test-service", enabled=True)
    assert tracer is not None
    same_tracer = get_tracer("test-service")
    assert same_tracer is not None
    shutdown_tracer()


def test_init_tracer_disabled():
    tracer = init_tracer(service_name="test-disabled", enabled=False)
    assert tracer is not None
    shutdown_tracer()


def test_trace_span_context_manager():
    init_tracer(service_name="test-span", enabled=True)

    with correlation_scope("corr-test-123"):
        with trace_span("test.operation", attributes={"custom.attr": "value"}) as span:
            assert span is not None
            # Context manager should run cleanly
            result = 1 + 1
            assert result == 2

    shutdown_tracer()


def test_trace_span_exception_recording():
    init_tracer(service_name="test-exception", enabled=True)

    with pytest.raises(ValueError, match="test error"):
        with trace_span("failing.operation"):
            raise ValueError("test error")

    shutdown_tracer()


@pytest.mark.asyncio
async def test_traced_decorator_async():
    init_tracer(service_name="test-decorator", enabled=True)

    @traced("test.async_func")
    async def async_sample(x: int, y: int) -> int:
        return x * y

    result = await async_sample(3, 4)
    assert result == 12
    shutdown_tracer()


def test_traced_decorator_sync():
    init_tracer(service_name="test-decorator-sync", enabled=True)

    @traced("test.sync_func")
    def sync_sample(a: str, b: str) -> str:
        return a + b

    result = sync_sample("hello ", "world")
    assert result == "hello world"
    shutdown_tracer()


def test_trace_context_injection_and_extraction():
    init_tracer(service_name="test-propagate", enabled=True)

    with trace_span("parent.span"):
        carrier = inject_trace_context()
        assert isinstance(carrier, dict)
        if "traceparent" in carrier:
            assert carrier["traceparent"].startswith("00-")

        extracted_context = extract_trace_context(carrier)
        assert extracted_context is not None

    shutdown_tracer()
