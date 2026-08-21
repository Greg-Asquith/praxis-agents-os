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
from services.agents.runtime.events import EVENT_TOOL_RESULT
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
from services.audit_events.enums import AuditStatus


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


def test_invalid_primary_salvages_valid_fallback_but_still_fails_closed() -> None:
    effects, evidence_valid = _recoverable_effects(
        _effect_metadata(primary="invalid", fallback=[_effect()])
    )

    assert effects[0].nested_call_id == "outer:1"
    assert evidence_valid is False


def test_malformed_state_container_is_invalid_effect_evidence() -> None:
    effects, evidence_valid = _recoverable_effects({CODE_MODE_STATE_METADATA_KEY: "invalid"})

    assert effects == []
    assert evidence_valid is False


def test_conflicting_valid_effect_ledgers_return_union_as_invalid_evidence() -> None:
    effects, evidence_valid = _recoverable_effects(
        _effect_metadata(primary=[_effect("outer:1")], fallback=[_effect("outer:2")])
    )

    assert [effect.nested_call_id for effect in effects] == ["outer:1", "outer:2"]
    assert evidence_valid is False


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        _effect_metadata(primary=[]),
        _effect_metadata(primary=[], fallback=[]),
    ],
)
def test_empty_or_absent_effect_evidence_remains_recoverable(metadata: dict[str, Any]) -> None:
    effects, evidence_valid = _recoverable_effects(metadata)

    assert effects == []
    assert evidence_valid is True


def test_valid_nonempty_effect_evidence_is_preserved() -> None:
    effects, evidence_valid = _recoverable_effects(_effect_metadata(primary=[_effect()]))

    assert effects[0].tool_name == "write"
    assert evidence_valid is True


async def test_read_only_oversized_suspension_returns_direct_call_guidance(
    executor: MontyExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES", 1)
    toolset = FunctionToolset([Tool(lambda: "ok", name="gated", requires_approval=True)])
    ctx = _ctx(toolset)

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer",
        code="await gated()",
        executor=executor,
    )

    assert result.return_value["status"] == "failed"
    assert "Call the tool directly" in result.return_value["error"]
    assert CODE_MODE_STATE_METADATA_KEY not in (ctx.deps.run.metadata_json or {})


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


async def test_oversized_second_suspension_clears_previous_state(
    executor: MontyExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolset = FunctionToolset([Tool(lambda value: value, name="gated", requires_approval=True)])
    ctx = _ctx(toolset)
    code = "await gated(value=1)\nawait gated(value=2)"
    with pytest.raises(ApprovalRequired) as first:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer",
            code=code,
            executor=executor,
        )
    args_sha256, _ = digest_args({"value": 1})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=first.value.metadata,
        decision="approved",
        effective_args={"value": 1},
        args_sha256=args_sha256,
        message=None,
    )
    monkeypatch.setattr(settings, "AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES", 1)

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer",
        code=code,
        executor=executor,
    )

    assert result.return_value["status"] == "failed"
    assert CODE_MODE_STATE_METADATA_KEY not in (ctx.deps.run.metadata_json or {})


@pytest.mark.parametrize("decision", ["approved", "denied"])
@pytest.mark.parametrize("effectful", [False, True], ids=["read_only", "effectful"])
async def test_load_failure_settles_decision_evidence_and_staged_cleanup(
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
    ctx.deps.run.metadata_json[CODE_MODE_STATE_METADATA_KEY]["snapshot_b64"] = "invalid"

    if effectful:
        with pytest.raises(CodeModeResumeRequiresRecoveryError) as exc_info:
            await execute_code_mode_workflow(
                ctx=ctx,
                wrapped_toolset=toolset,
                outer_tool_call_id="outer",
                code="await gated()",
                executor=executor,
            )
        assert exc_info.value.reason == "snapshot_corrupt"
    else:
        result = await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer",
            code="await gated()",
            executor=executor,
        )
        assert result.return_value["degradation_reason"] == "snapshot_corrupt"
    cleanup.assert_awaited_once()
    if decision == "denied":
        record_invocation.assert_awaited_once()
        assert record_invocation.await_args.kwargs["status"] == AuditStatus.DENIED
    else:
        record_invocation.assert_not_awaited()


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


async def test_stale_denial_does_not_settle_evidence(
    executor: MontyExecutor,
    monkeypatch: pytest.MonkeyPatch,
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
    decision_metadata = build_code_mode_decision_metadata(
        approval_metadata=pending.value.metadata,
        decision="denied",
        effective_args={},
        args_sha256=digest,
        message="No",
    )
    decision_metadata[CODE_MODE_DECISION_KEY]["nested_tool_call_id"] = "stale"
    ctx.tool_call_metadata = decision_metadata
    ctx.deps.workspace = SimpleNamespace(id=uuid4())
    record_invocation = AsyncMock()
    cleanup = AsyncMock()
    monkeypatch.setattr(bridge_module, "record_invocation", record_invocation)
    monkeypatch.setattr(bridge_module, "cleanup_staged_tool_content", cleanup)

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer",
        code="await gated()",
        executor=executor,
    )

    assert result.return_value["degradation_reason"] == "schema_mismatch"
    record_invocation.assert_not_awaited()
    cleanup.assert_not_awaited()


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
            "presentation_result": {"value": "one"},
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
            "presentation_result": "ONE",
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
    assert entry["presentation_result"] == {"password": secret, "payload": "x" * 2_000}


async def test_nested_trace_retains_every_complete_presentation_result() -> None:
    async def read_large(*, marker: str) -> dict[str, str]:
        return {"marker": marker, "payload": "x" * 22_000}

    bridge = await _bridge(FunctionToolset([Tool(read_large)]))
    call = bridge.external_lookup()["read_large"]
    for marker in ("one", "two", "three"):
        await call(marker=marker)

    result = bridge.finalize(ScriptExecution(result="done", output="", output_truncated=False))
    calls = result.metadata[CODE_MODE_TRACE_METADATA_KEY]["calls"]

    assert [entry["presentation_result"]["marker"] for entry in calls] == [
        "one",
        "two",
        "three",
    ]
    assert all(entry["presentation_result"]["payload"] == "x" * 22_000 for entry in calls)


async def test_large_fan_out_trace_retains_every_row_for_user_presentation() -> None:
    rows = [{"id": index, "payload": "x" * 3_000} for index in range(10)]

    async def read_report() -> dict[str, Any]:
        return {
            "results": [
                {
                    "connection_id": f"connection-{account}",
                    "data": {
                        "currency_code": "GBP",
                        "row_count": len(rows),
                        "rows": rows,
                        "truncated": False,
                        "truncation_note": None,
                    },
                    "display_name": f"Account {account}",
                    "error_code": None,
                    "error_message": None,
                    "external_id": str(account),
                    "status": "success",
                }
                for account in (1, 2)
            ]
        }

    bridge = await _bridge(FunctionToolset([Tool(read_report)]))
    await bridge.external_lookup()["read_report"]()
    result = bridge.finalize(ScriptExecution(result="done", output="", output_truncated=False))
    [entry] = result.metadata[CODE_MODE_TRACE_METADATA_KEY]["calls"]
    presentation = entry["presentation_result"]

    assert [len(item["data"]["rows"]) for item in presentation["results"]] == [10, 10]
    assert all(item["data"]["truncated"] is False for item in presentation["results"])
    assert all(item["data"]["truncation_note"] is None for item in presentation["results"])


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
        db=SimpleNamespace(commit=AsyncMock()),
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


async def test_nested_approval_suspends_instead_of_becoming_script_error(
    executor: MontyExecutor,
) -> None:
    toolset = FunctionToolset([Tool(lambda value: value, name="gated", requires_approval=True)])
    ctx = _ctx(toolset)

    with pytest.raises(ApprovalRequired) as exc_info:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code="await gated(value='x')",
            executor=executor,
        )

    assert exc_info.value.metadata["kind"] == "code_mode"
    assert exc_info.value.metadata["nested_tool_call_id"] == "outer-call:1"
    assert "code_mode_state" in ctx.deps.run.metadata_json


async def test_nested_approval_resumes_from_snapshot_in_fresh_executor(
    executor: MontyExecutor,
) -> None:
    calls: list[int] = []

    async def gated(value: int) -> int:
        calls.append(value)
        return value * 2

    toolset = FunctionToolset([Tool(gated, requires_approval=True)])
    ctx = _ctx(toolset)
    code = "value = await gated(value=21)\nvalue"
    with pytest.raises(ApprovalRequired) as exc_info:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code=code,
            executor=executor,
        )
    approval_metadata = exc_info.value.metadata
    args_sha256, _args_bytes = digest_args({"value": 21})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=approval_metadata,
        decision="approved",
        effective_args={"value": 21},
        args_sha256=args_sha256,
        message=None,
    )
    await executor.close()
    fresh_executor = MontyExecutor(
        pool_size=1,
        timeout_seconds=1,
        checkout_timeout_seconds=0.2,
        request_timeout_seconds=2,
        output_max_chars=100,
        memory_max_bytes=64 * 1024 * 1024,
        max_recursion_depth=100,
        gc_interval=1_000,
    )
    try:
        result = await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code=code,
            executor=fresh_executor,
        )
    finally:
        await fresh_executor.close()

    assert result.return_value == 42
    assert calls == [21]


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
async def test_persisted_read_only_continuation_without_valid_decision_fails_closed(
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
    ctx.tool_call_metadata = decision_metadata

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code="await gated()",
        executor=executor,
    )

    assert result.return_value["degradation_reason"] == "schema_mismatch"
    assert CODE_MODE_STATE_METADATA_KEY not in (ctx.deps.run.metadata_json or {})
    assert calls == 0


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


async def test_resume_preserves_print_output_before_and_after_approval(
    executor: MontyExecutor,
) -> None:
    toolset = FunctionToolset([Tool(lambda: "approved", name="gated", requires_approval=True)])
    ctx = _ctx(toolset)
    code = "print('before')\nvalue = await gated()\nprint('after')\nvalue"
    with pytest.raises(ApprovalRequired) as pending:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code=code,
            executor=executor,
        )
    args_sha256, _ = digest_args({})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=pending.value.metadata,
        decision="approved",
        effective_args={},
        args_sha256=args_sha256,
        message=None,
    )

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code=code,
        executor=executor,
    )

    assert result.return_value == {"output": "before\nafter\n", "result": "approved"}
    assert CODE_MODE_STATE_METADATA_KEY not in (ctx.deps.run.metadata_json or {})


async def test_two_approvals_accumulate_all_print_segments(
    executor: MontyExecutor,
) -> None:
    toolset = FunctionToolset([Tool(lambda value: value, name="gated", requires_approval=True)])
    ctx = _ctx(toolset)
    code = (
        "print('first')\n"
        "await gated(value=1)\n"
        "print('middle')\n"
        "await gated(value=2)\n"
        "print('last')\n"
        "'done'"
    )
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
    second_digest, _ = digest_args({"value": 2})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=second.value.metadata,
        decision="approved",
        effective_args={"value": 2},
        args_sha256=second_digest,
        message=None,
    )

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code=code,
        executor=executor,
    )

    assert result.return_value == {
        "output": "first\nmiddle\nlast\n",
        "result": "done",
    }


async def test_print_output_budget_does_not_reset_after_resume() -> None:
    bounded_executor = MontyExecutor(
        pool_size=1,
        timeout_seconds=1,
        checkout_timeout_seconds=0.2,
        request_timeout_seconds=2,
        output_max_chars=10,
        memory_max_bytes=64 * 1024 * 1024,
        max_recursion_depth=100,
        gc_interval=1_000,
    )
    toolset = FunctionToolset([Tool(lambda: "ok", name="gated", requires_approval=True)])
    ctx = _ctx(toolset)
    code = "print('1234567890')\nawait gated()\nprint('overflow')\n'done'"
    try:
        with pytest.raises(ApprovalRequired) as pending:
            await execute_code_mode_workflow(
                ctx=ctx,
                wrapped_toolset=toolset,
                outer_tool_call_id="outer-call",
                code=code,
                executor=bounded_executor,
            )
        args_sha256, _ = digest_args({})
        ctx.tool_call_metadata = build_code_mode_decision_metadata(
            approval_metadata=pending.value.metadata,
            decision="approved",
            effective_args={},
            args_sha256=args_sha256,
            message=None,
        )
        result = await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code=code,
            executor=bounded_executor,
        )
    finally:
        await bounded_executor.close()

    assert result.return_value == {"output": "1234567890", "result": "done"}
    assert result.metadata[CODE_MODE_TRACE_METADATA_KEY]["output_truncated"] is True


@pytest.mark.parametrize(
    "failure",
    [PermissionError("membership changed"), ToolFailed("provider rejected the write")],
)
async def test_approved_handler_failure_is_catchable_in_script(
    executor: MontyExecutor,
    failure: Exception,
) -> None:
    async def denied() -> str:
        raise failure

    toolset = FunctionToolset([Tool(denied, requires_approval=True)])
    ctx = _ctx(toolset)
    code = "try:\n    await denied()\nexcept RuntimeError as exc:\n    result = str(exc)\nresult"
    with pytest.raises(ApprovalRequired) as pending:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code=code,
            executor=executor,
        )
    args_sha256, _ = digest_args({})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=pending.value.metadata,
        decision="approved",
        effective_args={},
        args_sha256=args_sha256,
        message=None,
    )

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code=code,
        executor=executor,
    )

    assert str(failure) in result.return_value
    [trace_entry] = result.metadata[CODE_MODE_TRACE_METADATA_KEY]["calls"]
    assert trace_entry["status"] == "failed"


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


async def test_stale_nested_decision_keeps_schema_mismatch_reason(
    executor: MontyExecutor,
) -> None:
    toolset = FunctionToolset([Tool(lambda: "ok", name="gated", requires_approval=True)])
    ctx = _ctx(toolset)
    with pytest.raises(ApprovalRequired) as pending:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code="await gated()",
            executor=executor,
        )
    args_sha256, _ = digest_args({})
    decision = build_code_mode_decision_metadata(
        approval_metadata=pending.value.metadata,
        decision="approved",
        effective_args={},
        args_sha256=args_sha256,
        message=None,
    )
    decision[CODE_MODE_DECISION_KEY]["nested_tool_call_id"] = "stale"
    ctx.tool_call_metadata = decision

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code="await gated()",
        executor=executor,
    )

    assert result.return_value["degradation_reason"] == "schema_mismatch"


class _FailingResultSink(_RecordingSink):
    async def emit(self, payload: StreamEventPayload) -> None:
        if payload.event_name == EVENT_TOOL_RESULT:
            raise RuntimeError("event sink offline")
        await super().emit(payload)


async def test_operational_failure_during_settlement_is_labeled_resume_crash(
    executor: MontyExecutor,
) -> None:
    toolset = FunctionToolset([Tool(lambda: "ok", name="gated", requires_approval=True)])
    ctx = _ctx(toolset)
    with pytest.raises(ApprovalRequired) as pending:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code="await gated()",
            executor=executor,
        )
    args_sha256, _ = digest_args({})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=pending.value.metadata,
        decision="approved",
        effective_args={},
        args_sha256=args_sha256,
        message=None,
    )
    ctx.deps.sink = _FailingResultSink()

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code="await gated()",
        executor=executor,
    )

    assert result.return_value["degradation_reason"] == "resume_crash"
    assert CODE_MODE_STATE_METADATA_KEY not in (ctx.deps.run.metadata_json or {})


async def test_approved_nested_tool_preserves_public_result_on_resume(
    executor: MontyExecutor,
) -> None:
    public_result = {"rows": [{"id": 1}, {"id": 2}]}

    async def gated() -> ToolReturn[dict[str, str]]:
        return ToolReturn(
            return_value={"summary": "2 rows"},
            metadata={"public_result": public_result},
        )

    toolset = FunctionToolset([Tool(gated, requires_approval=True)])
    ctx = _ctx(toolset)
    with pytest.raises(ApprovalRequired) as exc_info:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code="await gated()",
            executor=executor,
        )
    args_sha256, _args_bytes = digest_args({})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=exc_info.value.metadata,
        decision="approved",
        effective_args={},
        args_sha256=args_sha256,
        message=None,
    )

    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code="await gated()",
        executor=executor,
    )

    [trace_entry] = result.metadata[CODE_MODE_TRACE_METADATA_KEY]["calls"]
    tool_result = next(
        event for event in reversed(ctx.deps.sink.events) if event.event == "tool.result"
    )
    assert result.return_value == {"summary": "2 rows"}
    assert trace_entry["presentation_result"] == public_result
    assert tool_result.data["result"] == public_result


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


async def test_nested_denial_is_catchable_and_does_not_invoke_handler(
    executor: MontyExecutor,
) -> None:
    handler_calls = 0

    async def handler(value: int) -> str:
        nonlocal handler_calls
        handler_calls += 1
        return "unexpected"

    toolset = FunctionToolset([Tool(handler, name="gated", requires_approval=True)])
    ctx = _ctx(toolset)
    code = (
        "try:\n    await gated(value=1)\nexcept PermissionError:\n    result = 'alternate'\nresult"
    )
    with pytest.raises(ApprovalRequired) as pending:
        await execute_code_mode_workflow(
            ctx=ctx,
            wrapped_toolset=toolset,
            outer_tool_call_id="outer-call",
            code=code,
            executor=executor,
        )
    denied_digest, _ = digest_args({"value": 1})
    ctx.tool_call_metadata = build_code_mode_decision_metadata(
        approval_metadata=pending.value.metadata,
        decision="denied",
        effective_args={"value": 1},
        args_sha256=denied_digest,
        message="Not now",
    )
    result = await execute_code_mode_workflow(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="outer-call",
        code=code,
        executor=executor,
    )

    assert result.return_value == "alternate"
    assert handler_calls == 0


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


async def test_nested_value_boundary_serializes_uuid_identifiers() -> None:
    resource_id = uuid4()

    async def value() -> dict[str, Any]:
        return {"integration_resource_id": resource_id}

    bridge = await _bridge(FunctionToolset([Tool(value)]))

    assert await bridge.external_lookup()["value"]() == {
        "integration_resource_id": str(resource_id)
    }


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


async def test_script_result_has_a_tighter_bound_than_nested_values() -> None:
    bridge = await _bridge(
        FunctionToolset([]),
        value_max_bytes=100,
        result_max_bytes=20,
    )

    with pytest.raises(CodeModeBoundaryError, match=r"run_workflow.*exceeds the 20-byte"):
        bridge.finalize(ScriptExecution(result="x" * 30, output="", output_truncated=False))


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
