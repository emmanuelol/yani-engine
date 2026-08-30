import asyncio
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from yani_engine.core.telemetry import (
    init_telemetry,
    shutdown_telemetry,
    trace_span,
    trace_async_step,
    record_token_metric,
    record_llm_latency,
    record_mcp_duration,
    record_circuit_breaker_event,
    get_logger,
)


@pytest.fixture(autouse=True)
def cleanup_telemetry():
    yield
    shutdown_telemetry()


@pytest.mark.asyncio
async def test_trace_span_with_in_memory_exporter():
    exporter = InMemorySpanExporter()
    init_telemetry(
        service_name="test-service",
        enable_telemetry=True,
        in_memory_exporter=exporter,
        debug=True,
    )

    async with trace_span("test.operation", {"custom.attr": "value123", "num.attr": 42}) as span:
        assert span.is_recording()
        await asyncio.sleep(0.01)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "test.operation"
    assert s.attributes["custom.attr"] == "value123"
    assert s.attributes["num.attr"] == 42
    assert s.status.status_code == StatusCode.OK


@pytest.mark.asyncio
async def test_trace_span_exception_recording():
    exporter = InMemorySpanExporter()
    init_telemetry(
        service_name="test-service",
        enable_telemetry=True,
        in_memory_exporter=exporter,
    )

    with pytest.raises(ValueError, match="Intentional failure"):
        async with trace_span("failing.operation", {"task.id": "T-999"}):
            raise ValueError("Intentional failure")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "failing.operation"
    assert s.status.status_code == StatusCode.ERROR
    assert len(s.events) >= 1
    assert s.events[0].name == "exception"


@pytest.mark.asyncio
async def test_trace_async_step_decorator():
    exporter = InMemorySpanExporter()
    init_telemetry(
        service_name="test-service",
        enable_telemetry=True,
        in_memory_exporter=exporter,
    )

    @trace_async_step("decorated.step", lambda a, b: {"param.a": a, "param.b": b})
    async def sample_func(a: str, b: int):
        await asyncio.sleep(0.01)
        return f"{a}:{b}"

    res = await sample_func("hello", 123)
    assert res == "hello:123"

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "decorated.step"
    assert spans[0].attributes["param.a"] == "hello"
    assert spans[0].attributes["param.b"] == 123


def test_metrics_and_events_do_not_crash_when_disabled():
    init_telemetry(enable_telemetry=False)
    # Should safely no-op without exceptions
    record_token_metric("gemini-3.6-flash", prompt_tokens=100, candidate_tokens=50, total_tokens=150)
    record_llm_latency("gemini-3.6-flash", 1.23, "success")
    record_mcp_duration("codegraph", "search_symbols", 0.45, "success")
    record_circuit_breaker_event("codegraph", "tripped", reason="Subprocess failed")


def test_metrics_and_events_when_enabled():
    init_telemetry(service_name="yani-test", enable_telemetry=True, debug=True)
    record_token_metric("gemini-3.6-flash", prompt_tokens=100, candidate_tokens=50, total_tokens=150)
    record_llm_latency("gemini-3.6-flash", 1.23, "success")
    record_mcp_duration("codegraph", "search_symbols", 0.45, "success")
    record_circuit_breaker_event("codegraph", "tripped", reason="Subprocess failed")
    log = get_logger("test")
    log.info("Test log emitted")


@pytest.mark.asyncio
async def test_mcp_manager_telemetry_integration(tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    from yani_engine.core.mcp_manager import PersistentCircuitBreaker, create_mcp_wrapper
    from types import SimpleNamespace

    exporter = InMemorySpanExporter()
    init_telemetry(service_name="test-mcp", enable_telemetry=True, in_memory_exporter=exporter)

    # 1. Test PersistentCircuitBreaker events
    cb = PersistentCircuitBreaker("test-server", threshold=2, state_dir=str(tmp_path))
    cb.record_failure(reason="Timeout")
    cb.record_failure(reason="Timeout 2")
    assert cb.is_open() is True
    cb.record_success()
    assert cb.is_open() is False

    # 2. Test create_mcp_wrapper span creation
    mock_session = AsyncMock()
    mock_session.call_tool.return_value = SimpleNamespace(
        content=[SimpleNamespace(text="Tool result payload")]
    )
    mock_tool = SimpleNamespace(name="find_references", inputSchema={"properties": {"query": {"type": "string"}}}, description="")
    sessions = {"test_srv": mock_session}
    locks = {}
    cfg = SimpleNamespace(max_parallel_tasks=2)

    wrapper = create_mcp_wrapper("test_srv", mock_tool, sessions, locks, cfg)
    res = await wrapper(query="TestClass")
    assert res == "Tool result payload"

    spans = exporter.get_finished_spans()
    tool_spans = [s for s in spans if s.name == "mcp.call_tool"]
    assert len(tool_spans) == 1
    assert tool_spans[0].attributes["mcp.server"] == "test_srv"
    assert tool_spans[0].attributes["mcp.tool"] == "find_references"
    assert tool_spans[0].attributes["mcp.status"] == "success"


@pytest.mark.asyncio
async def test_agent_runner_telemetry_integration():
    from unittest.mock import AsyncMock, MagicMock
    from types import SimpleNamespace
    from yani_engine.core.agent_loop import AgentRunner

    exporter = InMemorySpanExporter()
    init_telemetry(service_name="test-agent", enable_telemetry=True, in_memory_exporter=exporter)

    mock_orch = MagicMock()
    mock_orch.model = "gemini-3.6-flash"
    mock_orch.gemini_tools = []
    mock_orch.budget_manager.add_tokens = MagicMock()
    mock_orch.budget_manager.check_and_harvest = MagicMock()

    runner = AgentRunner(mock_orch)

    mock_provider = MagicMock()
    mock_response = SimpleNamespace(
        text="All done",
        usage_metadata=SimpleNamespace(
            prompt_token_count=40,
            candidates_token_count=20,
            total_token_count=60,
        ),
    )
    mock_provider.send_message = AsyncMock(return_value=mock_response)
    mock_provider.parse_tool_calls.return_value = []

    res = await runner._run_with_tools("session_obj", "Hello prompt", mock_provider, task_id="T-100")
    assert res == mock_response

    spans = exporter.get_finished_spans()
    llm_spans = [s for s in spans if s.name == "llm.send_message"]
    assert len(llm_spans) == 1
    assert llm_spans[0].attributes["llm.model"] == "gemini-3.6-flash"
    assert llm_spans[0].attributes["llm.retries"] == 0

