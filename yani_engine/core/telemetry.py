"""
telemetry.py — Centralized Observability & OpenTelemetry Tracing Engine.

Provides unified OpenTelemetry TracerProvider, MeterProvider, OTLP/Console
exporters, async span decorators, token usage metrics, circuit breaker events,
and structlog structured logging integration for yani-engine.
"""

from __future__ import annotations

import functools
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Optional

# Structured logging
import structlog

# OpenTelemetry API
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

_TRACER_PROVIDER: Optional[TracerProvider] = None
_METER_PROVIDER: Optional[MeterProvider] = None
_IS_INITIALIZED: bool = False

# Metric instruments
_TOKEN_COUNTER = None
_LLM_LATENCY_HISTOGRAM = None
_MCP_DURATION_HISTOGRAM = None
_CIRCUIT_BREAKER_COUNTER = None


def get_logger(name: str = "yani-engine") -> structlog.BoundLogger:
    """Returns a structlog bound logger configured for the application."""
    return structlog.get_logger(name)


def init_telemetry(
    service_name: str = "yani-engine",
    enable_telemetry: bool = False,
    otlp_endpoint: Optional[str] = None,
    log_format: str = "console",
    debug: bool = False,
    in_memory_exporter: Optional[Any] = None,
) -> None:
    """
    Initializes OpenTelemetry TracerProvider, MeterProvider, and structlog.
    If enable_telemetry is False, OpenTelemetry remains in default no-op mode.
    """
    global _TRACER_PROVIDER, _METER_PROVIDER, _IS_INITIALIZED
    global _TOKEN_COUNTER, _LLM_LATENCY_HISTOGRAM, _MCP_DURATION_HISTOGRAM, _CIRCUIT_BREAKER_COUNTER

    # 1. Configure structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(20 if not debug else 10),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if not enable_telemetry:
        _IS_INITIALIZED = False
        return

    # 2. Configure OpenTelemetry Resource
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "1.0.0",
            "deployment.environment": os.getenv("YANI_ENV", "development"),
        }
    )

    # 3. Configure TracerProvider & Exporter
    provider = TracerProvider(resource=resource)

    if in_memory_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(in_memory_exporter))
    elif otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, timeout=5)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception as e:
            get_logger().warning("Failed to initialize OTLP HTTP exporter, falling back to console", error=str(e))
            if debug:
                provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    elif debug:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    try:
        trace.set_tracer_provider(provider)
    except Exception:
        pass
    _TRACER_PROVIDER = provider

    # 4. Configure Metrics
    meter_provider = MeterProvider(resource=resource)
    try:
        metrics.set_meter_provider(meter_provider)
    except Exception:
        pass
    _METER_PROVIDER = meter_provider

    meter = meter_provider.get_meter(service_name)
    _TOKEN_COUNTER = meter.create_counter(
        name="yani_engine_llm_tokens_total",
        unit="tokens",
        description="Total tokens consumed by LLM interactions",
    )
    _LLM_LATENCY_HISTOGRAM = meter.create_histogram(
        name="yani_engine_llm_latency_seconds",
        unit="s",
        description="LLM request/response round-trip latency in seconds",
    )
    _MCP_DURATION_HISTOGRAM = meter.create_histogram(
        name="yani_engine_mcp_tool_duration_seconds",
        unit="s",
        description="MCP tool execution latency in seconds",
    )
    _CIRCUIT_BREAKER_COUNTER = meter.create_counter(
        name="yani_engine_circuit_breaker_events_total",
        unit="events",
        description="Total count of circuit breaker status transitions",
    )

    _IS_INITIALIZED = True
    get_logger().info("OpenTelemetry initialized", service_name=service_name, endpoint=otlp_endpoint)


def shutdown_telemetry() -> None:
    """Flushes and shuts down active TracerProvider and MeterProvider."""
    global _TRACER_PROVIDER, _METER_PROVIDER, _IS_INITIALIZED
    global _TOKEN_COUNTER, _LLM_LATENCY_HISTOGRAM, _MCP_DURATION_HISTOGRAM, _CIRCUIT_BREAKER_COUNTER
    if _TRACER_PROVIDER is not None:
        try:
            _TRACER_PROVIDER.shutdown()
        except Exception:
            pass
        _TRACER_PROVIDER = None

    if _METER_PROVIDER is not None:
        try:
            _METER_PROVIDER.shutdown()
        except Exception:
            pass
        _METER_PROVIDER = None

    _TOKEN_COUNTER = None
    _LLM_LATENCY_HISTOGRAM = None
    _MCP_DURATION_HISTOGRAM = None
    _CIRCUIT_BREAKER_COUNTER = None
    _IS_INITIALIZED = False


def get_tracer(name: str = "yani-engine") -> trace.Tracer:
    """Returns an OpenTelemetry tracer for span instrumentation."""
    if _TRACER_PROVIDER is not None:
        return _TRACER_PROVIDER.get_tracer(name)
    return trace.get_tracer(name)


@asynccontextmanager
async def trace_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """
    Async context manager that creates a child span with automatic timing and exception capture.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes and span.is_recording():
            for k, v in attributes.items():
                if v is not None:
                    span.set_attribute(k, str(v) if not isinstance(v, (bool, int, float, str)) else v)
        try:
            yield span
            if span.is_recording():
                span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            if span.is_recording():
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def trace_async_step(span_name: str, attributes_extractor: Optional[Callable[..., Dict[str, Any]]] = None):
    """
    Decorator for async methods/functions to create an active OpenTelemetry span.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            attrs = {}
            if attributes_extractor:
                try:
                    attrs = attributes_extractor(*args, **kwargs)
                except Exception:
                    pass
            async with trace_span(span_name, attrs):
                return await func(*args, **kwargs)
        return wrapper
    return decorator


def record_token_metric(model: str, prompt_tokens: int = 0, candidate_tokens: int = 0, total_tokens: int = 0) -> None:
    """Records LLM token consumption metrics across prompt, candidate, and total dimensions."""
    if _TOKEN_COUNTER is not None:
        if prompt_tokens > 0:
            _TOKEN_COUNTER.add(prompt_tokens, {"model": model, "token_type": "prompt"})
        if candidate_tokens > 0:
            _TOKEN_COUNTER.add(candidate_tokens, {"model": model, "token_type": "candidate"})
        if total_tokens > 0:
            _TOKEN_COUNTER.add(total_tokens, {"model": model, "token_type": "total"})


def record_llm_latency(model: str, latency_seconds: float, status: str = "success") -> None:
    """Records LLM round-trip execution latency."""
    if _LLM_LATENCY_HISTOGRAM is not None:
        _LLM_LATENCY_HISTOGRAM.record(latency_seconds, {"model": model, "status": status})


def record_mcp_duration(server: str, tool: str, duration_seconds: float, status: str = "success") -> None:
    """Records MCP RPC tool execution latency."""
    if _MCP_DURATION_HISTOGRAM is not None:
        _MCP_DURATION_HISTOGRAM.record(duration_seconds, {"server": server, "tool": tool, "status": status})


def record_circuit_breaker_event(server: str, event_type: str, reason: Optional[str] = None) -> None:
    """Records circuit breaker status transition events."""
    if _CIRCUIT_BREAKER_COUNTER is not None:
        attrs = {"server": server, "event": event_type}
        if reason:
            attrs["reason"] = str(reason)[:100]
        _CIRCUIT_BREAKER_COUNTER.add(1, attrs)
