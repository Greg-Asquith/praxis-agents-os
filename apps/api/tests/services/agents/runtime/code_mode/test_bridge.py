import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import (
    ApprovalRequired,
    ModelRetry,
    RunContext,
    Tool,
    ToolDenied,
    ToolReturn,
)
from pydantic_ai.messages import BinaryContent, ModelRequest, ToolCallPart, ToolReturnPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage

import services.agents.runtime.code_mode.bridge as bridge_module
from core.settings import settings
from services.agents.runtime.capabilities import build_runtime_capabilities
from services.agents.runtime.code_mode.approval import (
    CODE_MODE_DECISION_KEY,
    build_code_mode_decision_metadata,
)
from services.agents.runtime.code_mode.bridge import (
    CODE_MODE_TRACE_EXCERPT_MAX_CHARS,
    CODE_MODE_TRACE_METADATA_KEY,
    CodeModeBoundaryError,
    CodeModeBridge,
    _recoverable_effects,
    execute_code_mode_workflow,
)
from services.agents.runtime.code_mode.executor import MontyExecutor, ScriptExecution
from services.agents.runtime.code_mode.state import (
    CODE_MODE_STATE_EFFECT_LIMIT,
    CODE_MODE_STATE_METADATA_KEY,
    CodeModeResumeRequiresRecoveryError,
)
from services.agents.runtime.dispatch import digest_args
from services.agents.runtime.envelope import RunEnvelope
from services.agents.runtime.sinks import SinkEvent
from services.agents.runtime.stream_protocol import StreamEventPayload
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
    if not hasattr(resolved_deps, "run"):
        resolved_deps.run = SimpleNamespace(
            id=uuid4(),
            conversation_id=uuid4(),
            agent_id=uuid4(),
            metadata_json={},
        )
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

    async def emit(self, payload: StreamEventPayload) -> None:
        self.events.append(SinkEvent(event=payload.event_name, data=payload.serialize_payload()))

    async def close(self) -> None:
        return None


def _effect(call_id: str = "outer:1") -> dict[str, str]:
    return {
        "nested_call_id": call_id,
        "tool_name": "write",
        "args_sha256": "a" * 64,
    }


def _effect_metadata(*, primary: object = None, fallback: object = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if primary is not None:
        metadata[CODE_MODE_STATE_METADATA_KEY] = {"executed_effects": primary}
    if fallback is not None:
        metadata["approval_state"] = {
            "deferred_tool_requests": {
                "metadata": {"outer": {"kind": "code_mode", "executed_effects": fallback}}
            }
        }
    return metadata


@pytest.mark.parametrize(
    "primary",
    [
        [{"nested_call_id": "outer:1", "tool_name": "write"}],
        ["invalid"],
        "invalid",
        [_effect(str(index)) for index in range(CODE_MODE_STATE_EFFECT_LIMIT + 1)],
    ],
)
def test_malformed_effect_evidence_is_invalid(primary: object) -> None:
    effects, evidence_valid = _recoverable_effects(_effect_metadata(primary=primary))

    assert evidence_valid is False
    assert effects == []


def test_conflicting_valid_effect_ledgers_return_union_as_invalid_evidence() -> None:
    effects, evidence_valid = _recoverable_effects(
        _effect_metadata(primary=[_effect("outer:1")], fallback=[_effect("outer:2")])
    )

    assert [effect.nested_call_id for effect in effects] == ["outer:1", "outer:2"]
    assert evidence_valid is False


async def test_effectful_oversized_suspension_requires_operator_recovery(
    executor: MontyExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_name = f"code_mode_write_{uuid4().hex}"

    async def write() -> str:
        return "written"

    definition = RuntimeToolDefinition(
        name=tool_name,
        function=write,
        description="Write before approval.",
        effect=TOOL_EFFECT_WRITE,
    )
    RUNTIME_TOOL_CATALOG[tool_name] = definition
    monkeypatch.setattr(settings, "AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES", 1)
    toolset = FunctionToolset(
        [definition.to_pydantic_tool(), Tool(lambda: "ok", name="gated", requires_approval=True)]
    )
    ctx = _ctx(toolset)
    try:
        with pytest.raises(CodeModeResumeRequiresRecoveryError) as exc_info:
            await execute_code_mode_workflow(
                ctx=ctx,
                wrapped_toolset=toolset,
                outer_tool_call_id="outer",
                code=f"await {tool_name}()\nawait gated()",
                executor=executor,
            )
    finally:
        RUNTIME_TOOL_CATALOG.pop(tool_name, None)

    assert exc_info.value.reason == "snapshot_too_large"
    assert exc_info.value.executed_effects[0].tool_name == tool_name
    assert CODE_MODE_STATE_METADATA_KEY not in (ctx.deps.run.metadata_json or {})


@pytest.mark.parametrize("decision", ["approved", "denied"])
@pytest.mark.parametrize("effectful", [False, True], ids=["read_only", "effectful"])
async def test_resume_failure_settles_decision_evidence_and_staged_cleanup(
    executor: MontyExecutor,
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
    effectful: bool,
) -> None:
    toolset = FunctionToolset([Tool(lambda: "ok", name="gated", requires_approval=True)])
    ctx = _ctx(toolset)
    with pytest.raises(ApprovalRequired) as pending:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer",
            code="await gated()",
            executor=executor,
        )
    digest, _ = digest_args({})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=pending.value.metadata,
        decision=decision,
        effective_args={},
        args_sha256=digest,
        message="No" if decision == "denied" else None,
    )
    ctx.deps.workspace = SimpleNamespace(id=uuid4())
    record_invocation = AsyncMock()
    cleanup = AsyncMock()
    monkeypatch.setattr(bridge_module, "record_invocation", record_invocation)
    monkeypatch.setattr(bridge_module, "cleanup_staged_tool_content", cleanup)
    if effectful:
        ctx.deps.run.metadata_json[CODE_MODE_STATE_METADATA_KEY]["executed_effects"] = [
            {
                "nested_call_id": "outer:completed",
                "tool_name": "write",
                "args_sha256": "a" * 64,
            }
        ]
    failed_executor = SimpleNamespace(resume=AsyncMock(side_effect=TimeoutError("crashed")))

    if effectful:
        with pytest.raises(CodeModeResumeRequiresRecoveryError) as exc_info:
            await execute_code_mode_workflow(
                ctx=ctx,
                wrapped_toolset=toolset,
                outer_tool_call_id="outer",
                code="await gated()",
                executor=failed_executor,  # type: ignore[arg-type]
            )
        assert exc_info.value.reason == "resume_crash"
    else:
        result = await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer",
            code="await gated()",
            executor=failed_executor,  # type: ignore[arg-type]
        )
        assert result.return_value["degradation_reason"] == "resume_crash"
    cleanup.assert_awaited_once()
    if decision == "denied":
        record_invocation.assert_awaited_once()
    else:
        record_invocation.assert_not_awaited()


async def _bridge(
    toolset: FunctionToolset[Any],
    *,
    root_capability: Any = None,
    deps: Any = None,
    max_nested_calls: int = 25,
    value_max_bytes: int = 262_144,
    result_max_bytes: int | None = None,
) -> CodeModeBridge:
    return await CodeModeBridge.create(
        ctx=_ctx(toolset, root_capability=root_capability, deps=deps),
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        max_nested_calls=max_nested_calls,
        value_max_bytes=value_max_bytes,
        result_max_bytes=result_max_bytes,
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
    assert entry["presentation_result"] == {"password": secret, "payload": "x" * 2_000}


async def test_nested_tool_public_result_stays_user_visible_but_outside_sandbox() -> None:
    public_result = {"rows": [{"id": index, "value": "x" * 100} for index in range(20)]}

    async def summarized_result() -> ToolReturn[dict[str, str]]:
        return ToolReturn(
            return_value={"summary": "20 rows available"},
            metadata={"public_result": public_result},
        )

    deps = SimpleNamespace(sink=_RecordingSink())
    bridge = await _bridge(
        FunctionToolset([Tool(summarized_result)]),
        deps=deps,
        value_max_bytes=50,
    )

    sandbox_result = await bridge.external_lookup()["summarized_result"]()
    result = bridge.finalize(ScriptExecution(result="done", output="", output_truncated=False))
    [trace_entry] = result.metadata[CODE_MODE_TRACE_METADATA_KEY]["calls"]
    tool_result_event = next(event for event in deps.sink.events if event.event == "tool.result")

    assert sandbox_result == {"summary": "20 rows available"}
    assert trace_entry["presentation_result"] == public_result
    assert tool_result_event.data["result"] == public_result


async def test_tool_denied_is_not_treated_as_a_success() -> None:
    async def echo() -> str:
        return "unexpected"

    bridge = await _bridge(FunctionToolset([Tool(echo)]))
    bridge._manager.handle_call = AsyncMock(return_value=ToolDenied("operator denied"))  # type: ignore[method-assign]

    with pytest.raises(CodeModeBoundaryError, match="operator denied"):
        await bridge.external_lookup()["echo"]()


async def test_settled_workflow_does_not_turn_next_outer_call_into_continuation(
    executor: MontyExecutor,
) -> None:
    calls: list[int] = []

    async def gated(value: int) -> int:
        calls.append(value)
        return value

    toolset = FunctionToolset([Tool(gated, requires_approval=True)])
    ctx = _ctx(toolset)
    with pytest.raises(ApprovalRequired) as first:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="first-outer",
            code="await gated(value=1)",
            executor=executor,
        )
    first_digest, _ = digest_args({"value": 1})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=first.value.metadata,
        decision="approved",
        effective_args={"value": 1},
        args_sha256=first_digest,
        message=None,
    )
    await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="first-outer",
        code="await gated(value=1)",
        executor=executor,
    )
    ctx.tool_call_metadata = {}

    with pytest.raises(ApprovalRequired):
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="second-outer",
            code="await gated(value=2)",
            executor=executor,
        )

    assert calls == [1]
    assert (
        ctx.deps.run.metadata_json[CODE_MODE_STATE_METADATA_KEY]["outer_tool_call_id"]
        == "second-outer"
    )


async def test_second_workflow_suspension_fails_closed_without_overwriting_first(
    executor: MontyExecutor,
) -> None:
    calls: list[int] = []

    async def gated(value: int) -> int:
        calls.append(value)
        return value

    toolset = FunctionToolset([Tool(gated, requires_approval=True)])
    ctx = _ctx(toolset)
    with pytest.raises(ApprovalRequired) as first:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="first-outer",
            code="value = await gated(value=1)\nvalue",
            executor=executor,
        )
    persisted = dict(ctx.deps.run.metadata_json[CODE_MODE_STATE_METADATA_KEY])

    refused = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="second-outer",
        code="value = await gated(value=2)\nvalue",
        executor=executor,
    )

    assert refused.return_value["status"] == "failed"
    assert "already paused" in refused.return_value["error"]
    assert ctx.deps.run.metadata_json[CODE_MODE_STATE_METADATA_KEY] == persisted

    first_digest, _ = digest_args({"value": 1})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=first.value.metadata,
        decision="approved",
        effective_args={"value": 1},
        args_sha256=first_digest,
        message=None,
    )
    resumed = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="first-outer",
        code="value = await gated(value=1)\nvalue",
        executor=executor,
    )

    assert resumed.return_value == 1
    assert calls == [1]
    assert CODE_MODE_STATE_METADATA_KEY not in (ctx.deps.run.metadata_json or {})


@pytest.mark.parametrize("decision_metadata", [{}, {CODE_MODE_DECISION_KEY: "invalid"}])
async def test_persisted_effectful_continuation_without_valid_decision_requires_recovery(
    executor: MontyExecutor,
    decision_metadata: dict[str, Any],
) -> None:
    calls = 0

    async def gated() -> str:
        nonlocal calls
        calls += 1
        return "unexpected"

    toolset = FunctionToolset([Tool(gated, requires_approval=True)])
    ctx = _ctx(toolset)
    with pytest.raises(ApprovalRequired):
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code="await gated()",
            executor=executor,
        )
    state = ctx.deps.run.metadata_json[CODE_MODE_STATE_METADATA_KEY]
    state["executed_effects"] = [
        {"nested_call_id": "outer-call:0", "tool_name": "write", "args_sha256": "a" * 64}
    ]
    ctx.tool_call_metadata = decision_metadata

    with pytest.raises(CodeModeResumeRequiresRecoveryError) as exc_info:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code="await gated()",
            executor=executor,
        )

    assert exc_info.value.reason == "schema_mismatch"
    assert CODE_MODE_STATE_METADATA_KEY not in (ctx.deps.run.metadata_json or {})
    assert calls == 0


async def test_approved_argument_validation_failure_is_catchable_without_effect(
    executor: MontyExecutor,
) -> None:
    calls = 0

    async def gated(value: int) -> int:
        nonlocal calls
        calls += 1
        return value

    toolset = FunctionToolset([Tool(gated, requires_approval=True)])
    ctx = _ctx(toolset)
    code = "try:\n    await gated(value=1)\nexcept RuntimeError:\n    result = 'alternate'\nresult"
    with pytest.raises(ApprovalRequired) as pending:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code=code,
            executor=executor,
        )
    invalid_digest, _ = digest_args({"value": "invalid"})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=pending.value.metadata,
        decision="approved",
        effective_args={"value": "invalid"},
        args_sha256=invalid_digest,
        message=None,
    )

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code=code,
        executor=executor,
    )

    assert result.return_value == "alternate"
    assert calls == 0


async def test_one_nested_decision_does_not_approve_the_next_call(
    executor: MontyExecutor,
) -> None:
    calls: list[int] = []

    async def gated(value: int) -> int:
        calls.append(value)
        return value

    toolset = FunctionToolset([Tool(gated, requires_approval=True)])
    ctx = _ctx(toolset)
    code = "first = await gated(value=1)\nsecond = await gated(value=2)\nfirst + second"
    with pytest.raises(ApprovalRequired) as first:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code=code,
            executor=executor,
        )
    first_digest, _ = digest_args({"value": 1})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=first.value.metadata,
        decision="approved",
        effective_args={"value": 1},
        args_sha256=first_digest,
        message=None,
    )
    with pytest.raises(ApprovalRequired) as second:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code=code,
            executor=executor,
        )

    assert second.value.metadata["nested_tool_call_id"] == "outer-call:2"
    assert calls == [1]


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
    with pytest.raises(CodeModeBoundaryError, match=r"run_code.*exceeds the 5-byte"):
        bridge.finalize(ScriptExecution(result="too long", output="", output_truncated=False))


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
        "check_execution_permission",
        AsyncMock(),
    )
    deps = SimpleNamespace(
        execution_control=None,
        db=SimpleNamespace(commit=AsyncMock()),
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
        if side_effect_policy == "require_approval":
            with pytest.raises(ApprovalRequired):
                await bridge.external_lookup()[tool_name]()
        else:
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
                tool_name="run_code",
                tool_call_id="outer-call",
                content=result.return_value,
            )
        ]
    )
    [rendered] = render_untrusted_frames([request])
    assert UNTRUSTED_CONTENT_START in rendered.parts[0].content
