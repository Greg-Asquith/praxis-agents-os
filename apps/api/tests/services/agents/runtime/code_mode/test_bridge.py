import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import BaseModel
from pydantic_ai import (
    ApprovalRequired,
    ModelRetry,
    RunContext,
    Tool,
    ToolDenied,
    ToolFailed,
    ToolReturn,
)
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import BinaryContent, ModelRequest, ToolCallPart, ToolReturnPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage

from services.agents.runtime.capabilities import build_runtime_capabilities
from services.agents.runtime.code_mode.bridge import (
    CODE_MODE_TRACE_EXCERPT_MAX_CHARS,
    CODE_MODE_TRACE_METADATA_KEY,
    CodeModeBoundaryError,
    CodeModeBridge,
    execute_code_mode_workflow,
)
from services.agents.runtime.code_mode.executor import MontyExecutor, ScriptExecution
from services.agents.runtime.dispatch import digest_args
from services.agents.runtime.envelope import RunEnvelope
from services.agents.runtime.sinks import SinkEvent
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    RuntimeToolDefinition,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.agents.runtime.untrusted import (
    UNTRUSTED_CONTENT_START,
    UntrustedNode,
    render_untrusted_frames,
)


@pytest.fixture
def executor() -> MontyExecutor:
    return MontyExecutor(
        pool_size=1,
        timeout_seconds=1,
        checkout_timeout_seconds=0.2,
        request_timeout_seconds=2,
        output_max_chars=100,
        memory_max_bytes=64 * 1024 * 1024,
        max_recursion_depth=100,
        gc_interval=1_000,
    )


@pytest.fixture(autouse=True)
async def close_executor(executor: MontyExecutor):
    yield
    await executor.close()


def _ctx(
    toolset: FunctionToolset[Any],
    *,
    root_capability: Any = None,
    deps: Any = None,
) -> RunContext[Any]:
    resolved_deps = deps or SimpleNamespace(marker="deps")
    if not hasattr(resolved_deps, "sink"):
        resolved_deps.sink = _RecordingSink()
    ctx = RunContext(
        deps=resolved_deps,
        model=TestModel(),
        usage=RunUsage(),
    )
    ctx.tool_manager = ToolManager(
        toolset=toolset,
        root_capability=root_capability,
        ctx=ctx,
        tools={},
    )
    return ctx


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[SinkEvent] = []

    async def emit(self, event: str, payload: Any = None) -> None:
        self.events.append(SinkEvent(event=event, data=dict(payload or {})))

    async def close(self) -> None:
        return None


async def _bridge(
    toolset: FunctionToolset[Any],
    *,
    root_capability: Any = None,
    deps: Any = None,
    max_nested_calls: int = 25,
    value_max_bytes: int = 262_144,
) -> CodeModeBridge:
    return await CodeModeBridge.create(
        ctx=_ctx(toolset, root_capability=root_capability, deps=deps),
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        max_nested_calls=max_nested_calls,
        value_max_bytes=value_max_bytes,
    )


async def test_bridge_requires_parent_tool_manager() -> None:
    async def echo(value: str) -> str:
        return value

    toolset = FunctionToolset([Tool(echo)])
    ctx = RunContext(deps=object(), model=TestModel(), usage=RunUsage())

    with pytest.raises(RuntimeError, match="prepared parent ToolManager"):
        await CodeModeBridge.create(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
        )


async def test_nested_calls_are_serial_and_counter_is_cumulative(executor: MontyExecutor) -> None:
    active = 0
    max_active = 0

    async def echo(value: int) -> int:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return value

    toolset = FunctionToolset([Tool(echo)])
    ctx = _ctx(toolset)
    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code="import asyncio\nawait asyncio.gather(echo(value=1), echo(value=2))",
        executor=executor,
    )

    assert result.return_value == [1, 2]
    assert max_active == 1

    bridge = await _bridge(toolset, max_nested_calls=1)
    call = bridge.external_lookup()["echo"]
    assert await call(value=1) == 1
    with pytest.raises(CodeModeBoundaryError, match="nested call limit of 1"):
        await call(value=2)


async def test_two_call_workflow_emits_parented_events_and_bounded_trace(
    executor: MontyExecutor,
) -> None:
    async def first(*, value: str) -> dict[str, str]:
        return {"value": value}

    async def second(*, value: str) -> str:
        return value.upper()

    toolset = FunctionToolset([Tool(first), Tool(second)])
    ctx = _ctx(toolset)

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code=("first_result = await first(value='one')\nawait second(value=first_result['value'])"),
        executor=executor,
    )

    assert result.return_value == "ONE"
    assert [(event.event, event.data) for event in ctx.deps.sink.events] == [
        ("workflow.state", {"tool_call_id": "outer-call", "state": "started"}),
        (
            "tool.call",
            {
                "tool_call_id": "outer-call:1",
                "parent_tool_call_id": "outer-call",
                "name": "first",
                "args": {"value": "one"},
            },
        ),
        (
            "tool.result",
            {
                "tool_call_id": "outer-call:1",
                "parent_tool_call_id": "outer-call",
                "name": "first",
                "result": {"value": "one"},
            },
        ),
        (
            "tool.call",
            {
                "tool_call_id": "outer-call:2",
                "parent_tool_call_id": "outer-call",
                "name": "second",
                "args": {"value": "one"},
            },
        ),
        (
            "tool.result",
            {
                "tool_call_id": "outer-call:2",
                "parent_tool_call_id": "outer-call",
                "name": "second",
                "result": "ONE",
            },
        ),
        ("workflow.state", {"tool_call_id": "outer-call", "state": "completed"}),
    ]
    trace = result.metadata[CODE_MODE_TRACE_METADATA_KEY]
    assert trace["calls"] == [
        {
            "order": 1,
            "tool_call_id": "outer-call:1",
            "parent_tool_call_id": "outer-call",
            "tool_name": "first",
            "args_sha256": digest_args({"value": "one"})[0],
            "summary": "First",
            "status": "succeeded",
            "excerpt": '{"value":"one"}',
        },
        {
            "order": 2,
            "tool_call_id": "outer-call:2",
            "parent_tool_call_id": "outer-call",
            "tool_name": "second",
            "args_sha256": digest_args({"value": "one"})[0],
            "summary": "Second",
            "status": "succeeded",
            "excerpt": "ONE",
        },
    ]


async def test_nested_trace_excerpt_is_redacted_and_bounded(executor: MontyExecutor) -> None:
    secret = "secret-marker"

    async def read_large() -> dict[str, str]:
        return {"password": secret, "payload": "x" * 2_000}

    toolset = FunctionToolset([Tool(read_large)])
    result = await execute_code_mode_workflow(
        ctx=_ctx(toolset),
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code="await read_large()",
        executor=executor,
    )

    [entry] = result.metadata[CODE_MODE_TRACE_METADATA_KEY]["calls"]
    assert len(entry["excerpt"]) == CODE_MODE_TRACE_EXCERPT_MAX_CHARS
    assert "[REDACTED]" in entry["excerpt"]
    assert "[excerpt truncated]" in entry["excerpt"]
    assert secret not in entry["excerpt"]


async def test_workflow_state_output_and_error_excerpts_are_bounded() -> None:
    toolset: FunctionToolset[Any] = FunctionToolset([])
    completed_ctx = _ctx(toolset)
    completed_executor = SimpleNamespace(
        execute=AsyncMock(
            return_value=ScriptExecution(
                result="done",
                output="x" * 2_000,
                output_truncated=False,
            )
        )
    )

    await execute_code_mode_workflow(
        ctx=completed_ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="completed-call",
        code="'done'",
        executor=completed_executor,  # type: ignore[arg-type]
    )

    completed_event = completed_ctx.deps.sink.events[-1]
    assert completed_event.event == "workflow.state"
    assert completed_event.data["state"] == "completed"
    assert len(completed_event.data["output_excerpt"]) == CODE_MODE_TRACE_EXCERPT_MAX_CHARS

    failed_ctx = _ctx(toolset)
    failed_executor = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("y" * 2_000)))
    with pytest.raises(RuntimeError, match="yyy"):
        await execute_code_mode_workflow(
            ctx=failed_ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="failed-call",
            code="raise RuntimeError()",
            executor=failed_executor,  # type: ignore[arg-type]
        )

    failed_event = failed_ctx.deps.sink.events[-1]
    assert failed_event.event == "workflow.state"
    assert failed_event.data["state"] == "failed"
    assert len(failed_event.data["error_excerpt"]) == CODE_MODE_TRACE_EXCERPT_MAX_CHARS


async def test_nested_dispatch_audits_each_call_with_parent_and_effective_args_digest(
    executor: MontyExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def first(*, value: str) -> dict[str, str]:
        return {"value": value}

    async def second(*, value: str = "default") -> str:
        return value

    definitions = [
        RuntimeToolDefinition(
            name="code_mode_audit_first",
            function=first,
            description="First audited read.",
        ),
        RuntimeToolDefinition(
            name="code_mode_audit_second",
            function=second,
            description="Second audited read.",
        ),
    ]
    for definition in definitions:
        RUNTIME_TOOL_CATALOG[definition.name] = definition

    dispatch_module = __import__(
        "services.agents.runtime.dispatch",
        fromlist=["dispatch_tool_execution"],
    )
    monkeypatch.setattr(dispatch_module, "_active_workspace_role", AsyncMock(return_value="member"))
    record_invocation = AsyncMock()
    monkeypatch.setattr(dispatch_module, "record_invocation", record_invocation)
    monkeypatch.setattr(dispatch_module, "raise_if_agent_run_cancelled", AsyncMock())
    deps = SimpleNamespace(
        db=object(),
        membership=SimpleNamespace(id=uuid4()),
        workspace=SimpleNamespace(id=uuid4()),
        user=SimpleNamespace(id=uuid4()),
        run=SimpleNamespace(id=uuid4()),
        agent=SimpleNamespace(),
        envelope=RunEnvelope(principal="interactive", side_effect_policy="allow"),
    )
    toolset = FunctionToolset([definition.to_pydantic_tool() for definition in definitions])
    hooks = build_runtime_capabilities(SimpleNamespace())[0]

    try:
        await execute_code_mode_workflow(
            ctx=_ctx(toolset, root_capability=hooks, deps=deps),
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code=(
                "item = await code_mode_audit_first(value='one')\n"
                "await code_mode_audit_second(value=item['value'])"
            ),
            executor=executor,
        )

        assert [call.kwargs["tool_name"] for call in record_invocation.await_args_list] == [
            "code_mode_audit_first",
            "code_mode_audit_second",
        ]
        assert [
            call.kwargs["parent_tool_call_id"] for call in record_invocation.await_args_list
        ] == ["outer-call", "outer-call"]
        assert [call.kwargs["args_sha256"] for call in record_invocation.await_args_list] == [
            digest_args({"value": "one"})[0],
            digest_args({"value": "one"})[0],
        ]
    finally:
        for definition in definitions:
            RUNTIME_TOOL_CATALOG.pop(definition.name, None)


async def test_bridge_uses_keyword_arguments_only() -> None:
    async def echo(value: int) -> int:
        return value

    bridge = await _bridge(FunctionToolset([Tool(echo)]))
    with pytest.raises(CodeModeBoundaryError, match="passed by keyword"):
        await bridge.external_lookup()["echo"](1)


async def test_tool_denied_is_not_treated_as_a_success() -> None:
    async def echo() -> str:
        return "unexpected"

    bridge = await _bridge(FunctionToolset([Tool(echo)]))
    bridge._manager.handle_call = AsyncMock(return_value=ToolDenied("operator denied"))  # type: ignore[method-assign]

    with pytest.raises(CodeModeBoundaryError, match="operator denied"):
        await bridge.external_lookup()["echo"]()


@pytest.mark.parametrize(
    ("tool_factory", "message", "expected_status"),
    [
        (
            lambda: Tool(lambda value: value, name="gated", requires_approval=True),
            "tool requires approval",
            "pending",
        ),
        (
            lambda: Tool(lambda value: (_ for _ in ()).throw(ModelRetry("retry me")), name="retry"),
            "retry me",
            "failed",
        ),
        (
            lambda: Tool(
                lambda value: (_ for _ in ()).throw(ToolFailed("failed once")), name="failed"
            ),
            "failed once",
            "failed",
        ),
    ],
)
async def test_nested_control_flow_becomes_catchable_script_error(
    executor: MontyExecutor,
    tool_factory: Callable[[], Tool[Any]],
    message: str,
    expected_status: str,
) -> None:
    tool = tool_factory()
    toolset = FunctionToolset([tool])
    ctx = _ctx(toolset)
    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code=(
            f"try:\n    await {tool.name}(value='x')\n"
            "except RuntimeError as exc:\n    result = str(exc)\nresult"
        ),
        executor=executor,
    )

    assert message in result.return_value
    [trace_entry] = result.metadata[CODE_MODE_TRACE_METADATA_KEY]["calls"]
    assert trace_entry["status"] == expected_status
    assert message in trace_entry["excerpt"]
    assert ctx.retries == {}


async def test_raw_argument_validation_is_catchable_without_retry_budget(
    executor: MontyExecutor,
) -> None:
    async def integer(value: int) -> int:
        return value

    toolset = FunctionToolset([Tool(integer, name="integer")])
    ctx = _ctx(toolset)
    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code=(
            "try:\n    await integer(value='not-an-int')\n"
            "except RuntimeError as exc:\n    result = str(exc)\nresult"
        ),
        executor=executor,
    )

    assert "valid integer" in result.return_value
    assert ctx.retries == {}


@pytest.mark.parametrize(
    ("returned", "message"),
    [
        (b"binary", "not JSON-safe"),
        ({1, 2}, "not JSON-safe"),
        ("x" * 50, "exceeds the 20-byte"),
        (
            ToolReturn(
                return_value="summary",
                content=[BinaryContent(data=b"png", media_type="image/png")],
            ),
            "binary or multimodal",
        ),
    ],
)
async def test_nested_value_boundary_failures_are_structured(
    returned: Any,
    message: str,
) -> None:
    async def value() -> Any:
        return returned

    bridge = await _bridge(FunctionToolset([Tool(value)]), value_max_bytes=20)
    with pytest.raises(CodeModeBoundaryError, match=message):
        await bridge.external_lookup()["value"]()


@pytest.mark.parametrize("argument", [b"binary", "x" * 50])
async def test_nested_arguments_are_independently_byte_bounded(argument: Any) -> None:
    async def value(payload: Any) -> Any:
        return payload

    bridge = await _bridge(FunctionToolset([Tool(value)]), value_max_bytes=20)
    with pytest.raises(CodeModeBoundaryError, match="value"):
        await bridge.external_lookup()["value"](payload=argument)


async def test_script_result_value_boundary_is_enforced() -> None:
    toolset: FunctionToolset[Any] = FunctionToolset([])
    ctx = _ctx(toolset)

    bridge = await CodeModeBridge.create(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        value_max_bytes=5,
    )
    with pytest.raises(CodeModeBoundaryError, match=r"run_workflow.*exceeds the 5-byte"):
        bridge.finalize(ScriptExecution(result="too long", output="", output_truncated=False))


async def test_direct_and_nested_calls_share_framework_tool_contract() -> None:
    hook_calls: list[tuple[str, dict[str, Any]]] = []
    validator_calls: list[int] = []
    handler_calls: list[tuple[str, int, str]] = []
    hooks = Hooks()

    @hooks.on.tool_execute
    async def observe(ctx, *, call, tool_def, args, handler):
        hook_calls.append((call.tool_call_id, dict(args)))
        return await handler(args)

    def validate(_ctx: RunContext[Any], value: int, suffix: str = "default") -> None:
        validator_calls.append(value)
        if value < 0:
            raise ModelRetry("value must be positive")

    async def contract_tool(
        ctx: RunContext[Any],
        value: int,
        suffix: str = "default",
    ) -> dict[str, Any]:
        handler_calls.append((ctx.deps.marker, value, suffix))
        return {"marker": ctx.deps.marker, "value": value, "suffix": suffix}

    tool = Tool(
        contract_tool,
        takes_ctx=True,
        args_validator=validate,
        timeout=0.2,
    )
    toolset = FunctionToolset([tool])
    ctx = _ctx(toolset, root_capability=hooks)
    direct_manager = ToolManager(
        toolset=toolset,
        root_capability=hooks,
        ctx=ctx,
        tools=await toolset.get_tools(ctx),
    )
    direct = await direct_manager.handle_call(
        ToolCallPart(
            tool_name="contract_tool",
            args={"value": "2"},
            tool_call_id="direct",
        ),
        wrap_validation_errors=False,
    )

    bridge = await CodeModeBridge.create(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
    )
    nested = await bridge.external_lookup()["contract_tool"](value="2")

    expected = {"marker": "deps", "value": 2, "suffix": "default"}
    assert direct == expected
    assert nested == expected
    assert validator_calls == [2, 2]
    assert handler_calls == [("deps", 2, "default"), ("deps", 2, "default")]
    assert hook_calls == [
        ("direct", {"value": 2, "suffix": "default"}),
        ("outer-call:1", {"value": 2, "suffix": "default"}),
    ]


async def test_direct_and_nested_calls_share_tool_timeout() -> None:
    async def slow() -> None:
        await asyncio.Event().wait()

    tool = Tool(slow, timeout=0.01)
    toolset = FunctionToolset([tool])
    ctx = _ctx(toolset)
    direct_manager = ToolManager(
        toolset=toolset,
        ctx=ctx,
        tools=await toolset.get_tools(ctx),
    )
    with pytest.raises(ModelRetry, match=r"Timed out after 0\.01 seconds"):
        await direct_manager.handle_call(
            ToolCallPart(tool_name="slow", args={}, tool_call_id="direct"),
            wrap_validation_errors=False,
        )

    bridge = await CodeModeBridge.create(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
    )
    with pytest.raises(CodeModeBoundaryError, match=r"Timed out after 0\.01 seconds"):
        await bridge.external_lookup()["slow"]()


@pytest.mark.parametrize(
    ("role", "side_effect_policy", "expected"),
    [
        ("read_only", "allow", "workspace role is read-only"),
        ("member", "deny", "side-effect policy"),
        ("member", "require_approval", "tool requires approval"),
    ],
)
async def test_nested_calls_reach_praxis_authorization_and_envelope_hooks(
    monkeypatch,
    role: str,
    side_effect_policy: str,
    expected: str,
) -> None:
    tool_name = f"code_mode_policy_{uuid4().hex}"
    handler_calls = 0

    async def handler() -> dict[str, bool]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    definition = RuntimeToolDefinition(
        name=tool_name,
        function=handler,
        description="Policy parity test.",
        effect=TOOL_EFFECT_WRITE,
        effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
        egress=TOOL_EGRESS_EXTERNAL_WRITE,
    )
    RUNTIME_TOOL_CATALOG[tool_name] = definition
    dispatch_module = __import__(
        "services.agents.runtime.dispatch",
        fromlist=["dispatch_tool_execution"],
    )
    monkeypatch.setattr(dispatch_module, "_active_workspace_role", AsyncMock(return_value=role))
    record_invocation = AsyncMock()
    monkeypatch.setattr(dispatch_module, "record_invocation", record_invocation)
    monkeypatch.setattr(
        dispatch_module,
        "raise_if_agent_run_cancelled",
        AsyncMock(),
    )
    deps = SimpleNamespace(
        db=object(),
        membership=SimpleNamespace(id=uuid4()),
        workspace=SimpleNamespace(id=uuid4()),
        user=SimpleNamespace(id=uuid4()),
        run=SimpleNamespace(id=uuid4()),
        agent=SimpleNamespace(),
        envelope=RunEnvelope(principal="interactive", side_effect_policy=side_effect_policy),
    )
    toolset = FunctionToolset([definition.to_pydantic_tool()])
    hooks = build_runtime_capabilities(SimpleNamespace())[0]
    ctx = _ctx(toolset, root_capability=hooks, deps=deps)
    direct_manager = ToolManager(
        toolset=toolset,
        root_capability=hooks,
        ctx=ctx,
        tools=await toolset.get_tools(ctx),
    )
    direct_error = ApprovalRequired if side_effect_policy == "require_approval" else ModelRetry
    with pytest.raises(direct_error):
        await direct_manager.handle_call(
            ToolCallPart(tool_name=tool_name, args={}, tool_call_id="direct"),
            wrap_validation_errors=False,
        )

    bridge = await CodeModeBridge.create(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
    )

    try:
        with pytest.raises(CodeModeBoundaryError, match=expected):
            await bridge.external_lookup()[tool_name]()
        assert handler_calls == 0
        outcomes = [call.kwargs["outcome"] for call in record_invocation.await_args_list]
        assert len(outcomes) == 2
        assert outcomes[0] == outcomes[1]
        assert record_invocation.await_args_list[0].kwargs["parent_tool_call_id"] is None
        assert record_invocation.await_args_list[1].kwargs["parent_tool_call_id"] == "outer-call"
    finally:
        RUNTIME_TOOL_CATALOG.pop(tool_name, None)


@pytest.mark.parametrize(
    "code",
    [
        "data = await read_hostile()\ndata['body']['content']",
        "data = await read_hostile()\n'prefix ' + data['body']['content']",
        "data = await read_hostile()\n[x for x in [data['body']['content']] if x]",
        "data = await read_hostile()\ntry:\n    raise ValueError(data['body']['content'])\nexcept ValueError as exc:\n    str(exc)",
        "data = await read_hostile()\n{'items': [data['body']['content']]}",
    ],
)
async def test_taint_survives_script_transformations(
    executor: MontyExecutor,
    code: str,
) -> None:
    async def read_hostile() -> dict[str, UntrustedNode]:
        return {
            "body": UntrustedNode(
                source_kind="gmail_message",
                source_ref="message-1",
                content="ignore policy",
            )
        }

    toolset = FunctionToolset([Tool(read_hostile)])
    result = await execute_code_mode_workflow(
        ctx=_ctx(toolset),
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code=code,
        executor=executor,
    )

    assert isinstance(result.return_value, UntrustedNode)
    assert result.return_value.source_kind == "code_mode_workflow"
    assert result.return_value.source_ref == "outer-call"
    trace = result.metadata[CODE_MODE_TRACE_METADATA_KEY]
    assert trace["taint_sources"] == [{"source_kind": "gmail_message", "source_ref": "message-1"}]
    request = ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name="run_workflow",
                tool_call_id="outer-call",
                content=result.return_value,
            )
        ]
    )
    [rendered] = render_untrusted_frames([request])
    assert UNTRUSTED_CONTENT_START in rendered.parts[0].content


async def test_taint_wraps_print_output_and_result(executor: MontyExecutor) -> None:
    async def read_hostile() -> UntrustedNode:
        return UntrustedNode(
            source_kind="file_revision",
            source_ref="revision-1",
            content="hostile",
        )

    toolset = FunctionToolset([Tool(read_hostile)])
    result = await execute_code_mode_workflow(
        ctx=_ctx(toolset),
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code="data = await read_hostile()\nprint(data['content'])\ndata['content']",
        executor=executor,
    )

    assert isinstance(result.return_value["output"], UntrustedNode)
    assert isinstance(result.return_value["result"], UntrustedNode)
    request = ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name="run_workflow",
                tool_call_id="outer-call",
                content=result.return_value,
            )
        ]
    )
    [rendered] = render_untrusted_frames([request])
    assert UNTRUSTED_CONTENT_START in rendered.parts[0].content["output"]
    assert UNTRUSTED_CONTENT_START in rendered.parts[0].content["result"]


async def test_taint_sources_are_bounded_with_an_overflow_count(executor: MontyExecutor) -> None:
    async def read_many() -> list[UntrustedNode]:
        return [
            UntrustedNode(
                source_kind="file_revision",
                source_ref=f"revision-{index}",
                content=str(index),
            )
            for index in range(34)
        ]

    toolset = FunctionToolset([Tool(read_many)])
    result = await execute_code_mode_workflow(
        ctx=_ctx(toolset),
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code="values = await read_many()\nlen(values)",
        executor=executor,
    )

    trace = result.metadata[CODE_MODE_TRACE_METADATA_KEY]
    assert len(trace["taint_sources"]) == 32
    assert trace["taint_sources_overflow"] == 2


async def test_taint_is_detected_inside_pydantic_results(executor: MontyExecutor) -> None:
    class WrappedNode(BaseModel):
        body: UntrustedNode

    async def read_wrapped() -> WrappedNode:
        return WrappedNode(
            body=UntrustedNode(
                source_kind="kb_document",
                source_ref="document-1",
                content="hostile",
            )
        )

    toolset = FunctionToolset([Tool(read_wrapped)])
    result = await execute_code_mode_workflow(
        ctx=_ctx(toolset),
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code="data = await read_wrapped()\ndata['body']['content']",
        executor=executor,
    )

    assert isinstance(result.return_value, UntrustedNode)
    assert result.metadata[CODE_MODE_TRACE_METADATA_KEY]["taint_sources"] == [
        {"source_kind": "kb_document", "source_ref": "document-1"}
    ]


async def test_untainted_script_stays_unwrapped(executor: MontyExecutor) -> None:
    async def read_safe() -> dict[str, int]:
        return {"value": 42}

    toolset = FunctionToolset([Tool(read_safe)])
    result = await execute_code_mode_workflow(
        ctx=_ctx(toolset),
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code="await read_safe()",
        executor=executor,
    )

    assert result.return_value == {"value": 42}
    assert result.metadata[CODE_MODE_TRACE_METADATA_KEY]["tainted"] is False
