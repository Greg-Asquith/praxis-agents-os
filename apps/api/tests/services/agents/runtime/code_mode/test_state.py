import copy
import json
from uuid import uuid4

import pytest
from pydantic_monty import AsyncMonty, MontyCrashedError

from models.agent_run import AgentRun
from services.agents.runtime.code_mode.state import (
    CODE_MODE_MONTY_VERSION,
    CODE_MODE_STATE_EFFECT_LIMIT,
    CODE_MODE_STATE_METADATA_KEY,
    CODE_MODE_STATE_TAINT_SOURCE_LIMIT,
    CODE_MODE_STATE_TRACE_LIMIT,
    CodeModeStateError,
    append_executed_effect,
    build_code_mode_state_metadata,
    classify_snapshot_load_failure,
    clear_code_mode_state_metadata,
    load_code_mode_state,
)

MAX_BYTES = 1024
MAX_STATE_BYTES = 2 * 1024 * 1024


def _run() -> AgentRun:
    return AgentRun(
        id=uuid4(),
        conversation_id=uuid4(),
        agent_id=uuid4(),
        workspace_id=uuid4(),
        user_id=uuid4(),
        trigger="interactive",
        status="running",
        metadata_json={"kept": True},
    )


def _metadata(run: AgentRun) -> dict:
    return build_code_mode_state_metadata(
        run=run,
        outer_tool_call_id="workflow-1",
        nested_call_id="workflow-1:2",
        code="await update(value=2)",
        reason="Approval required",
        snapshot=b"snapshot",
        executed_call_count=2,
        elapsed_seconds=1.25,
        executed_effects=[
            {"nested_call_id": "workflow-1:1", "tool_name": "update", "args_sha256": "abc"}
        ],
        nested_trace=[
            {
                "order": 1,
                "tool_call_id": "workflow-1:1",
                "parent_tool_call_id": "workflow-1",
                "tool_name": "update",
                "args_sha256": "abc",
                "summary": "Update",
                "status": "succeeded",
                "excerpt": "done",
            }
        ],
        tainted=True,
        taint_sources=[{"source_kind": "integration", "source_ref": "row-1"}],
        taint_sources_overflow=1,
        output="before approval\n",
        output_truncated=False,
        snapshot_max_bytes=MAX_BYTES,
        state_max_bytes=MAX_STATE_BYTES,
    )


def test_code_mode_state_round_trip_including_taint_and_effects() -> None:
    run = _run()
    run.metadata_json = _metadata(run)

    state = load_code_mode_state(run, outer_tool_call_id="workflow-1", snapshot_max_bytes=MAX_BYTES)

    assert state.snapshot == b"snapshot"
    assert state.consumed_budget.nested_calls == 2
    assert state.executed_effects[0].tool_name == "update"
    assert state.tainted is True
    assert state.taint_sources[0]["source_ref"] == "row-1"
    assert state.output == "before approval\n"
    assert state.output_truncated is False
    assert (
        run.metadata_json[CODE_MODE_STATE_METADATA_KEY]["monty_version"] == CODE_MODE_MONTY_VERSION
    )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda run: run.metadata_json.pop(CODE_MODE_STATE_METADATA_KEY), "missing_key"),
        (
            lambda run: run.metadata_json[CODE_MODE_STATE_METADATA_KEY].update(version=999),
            "schema_mismatch",
        ),
        (
            lambda run: run.metadata_json[CODE_MODE_STATE_METADATA_KEY].update(
                monty_version="0.0.0"
            ),
            "monty_version_mismatch",
        ),
        (
            lambda run: run.metadata_json[CODE_MODE_STATE_METADATA_KEY].update(snapshot_b64="%%%"),
            "snapshot_corrupt",
        ),
        (
            lambda run: run.metadata_json[CODE_MODE_STATE_METADATA_KEY].update(run_id=str(uuid4())),
            "schema_mismatch",
        ),
    ],
)
def test_load_failure_has_typed_reason(mutate, reason: str) -> None:
    run = _run()
    run.metadata_json = copy.deepcopy(_metadata(run))
    mutate(run)

    with pytest.raises(CodeModeStateError) as exc_info:
        load_code_mode_state(run, snapshot_max_bytes=MAX_BYTES)

    assert exc_info.value.reason == reason


def test_snapshot_bound_is_applied_before_base64_storage() -> None:
    run = _run()
    with pytest.raises(CodeModeStateError) as exc_info:
        build_code_mode_state_metadata(
            run=run,
            outer_tool_call_id="outer",
            nested_call_id="nested",
            code="pass",
            reason=None,
            snapshot=b"x" * 11,
            executed_call_count=0,
            elapsed_seconds=0,
            executed_effects=[],
            nested_trace=[],
            output="",
            output_truncated=False,
            snapshot_max_bytes=10,
            state_max_bytes=MAX_STATE_BYTES,
        )
    assert run.metadata_json == {"kept": True}
    assert exc_info.value.reason == "snapshot_too_large"


def test_maximum_state_is_trimmed_to_the_aggregate_bound() -> None:
    snapshot_max_bytes = 512 * 1024
    output_max_chars = 8_000
    run = _run()
    metadata = build_code_mode_state_metadata(
        run=run,
        outer_tool_call_id="outer",
        nested_call_id="nested",
        code="await write(value='x')",
        reason="Approval required",
        snapshot=b"x" * snapshot_max_bytes,
        executed_call_count=CODE_MODE_STATE_TRACE_LIMIT,
        elapsed_seconds=60,
        executed_effects=[
            {
                "nested_call_id": f"call-{index}",
                "tool_name": "write",
                "args_sha256": "a" * 64,
            }
            for index in range(CODE_MODE_STATE_EFFECT_LIMIT)
        ],
        nested_trace=[
            {
                "order": index + 1,
                "tool_call_id": f"call-{index}",
                "parent_tool_call_id": "outer",
                "tool_name": "write",
                "args_sha256": "a" * 64,
                "summary": "Write",
                "status": "succeeded",
                "excerpt": "completed",
                "presentation_result": {"content": "p" * (256 * 1024)},
            }
            for index in range(CODE_MODE_STATE_TRACE_LIMIT)
        ],
        taint_sources=[
            {"source_kind": "integration", "source_ref": f"source-{index}"}
            for index in range(CODE_MODE_STATE_TAINT_SOURCE_LIMIT)
        ],
        output="o" * output_max_chars,
        output_truncated=True,
        snapshot_max_bytes=snapshot_max_bytes,
        state_max_bytes=MAX_STATE_BYTES,
    )

    serialized = json.dumps(metadata[CODE_MODE_STATE_METADATA_KEY]).encode()
    assert len(serialized) <= MAX_STATE_BYTES
    trace = metadata[CODE_MODE_STATE_METADATA_KEY]["nested_trace"]
    assert trace[0]["presentation_truncated"] is True
    assert "presentation_result" not in trace[0]
    assert trace[-1]["presentation_result"]["content"]
    assert "presentation_truncated" not in trace[-1]


def test_single_unbounded_presentation_is_trimmed_from_durable_state() -> None:
    run = _run()
    metadata = build_code_mode_state_metadata(
        run=run,
        outer_tool_call_id="outer",
        nested_call_id="nested",
        code="await read()",
        reason=None,
        snapshot=b"snapshot",
        executed_call_count=1,
        elapsed_seconds=0,
        executed_effects=[],
        nested_trace=[
            {
                "order": 1,
                "tool_call_id": "nested",
                "parent_tool_call_id": "outer",
                "tool_name": "read",
                "args_sha256": "a" * 64,
                "summary": "Read",
                "status": "succeeded",
                "excerpt": "complete",
                "presentation_result": {"content": "x" * (3 * 1024 * 1024)},
            }
        ],
        snapshot_max_bytes=MAX_BYTES,
        state_max_bytes=MAX_STATE_BYTES,
    )

    [entry] = metadata[CODE_MODE_STATE_METADATA_KEY]["nested_trace"]
    assert entry["presentation_truncated"] is True
    assert "presentation_result" not in entry


def test_state_that_cannot_fit_after_presentation_trimming_fails_closed() -> None:
    run = _run()
    with pytest.raises(CodeModeStateError) as exc_info:
        build_code_mode_state_metadata(
            run=run,
            outer_tool_call_id="outer",
            nested_call_id="nested",
            code="await read()",
            reason=None,
            snapshot=b"snapshot",
            executed_call_count=0,
            elapsed_seconds=0,
            executed_effects=[],
            nested_trace=[],
            snapshot_max_bytes=MAX_BYTES,
            state_max_bytes=10,
        )
    assert exc_info.value.reason == "snapshot_too_large"


@pytest.mark.parametrize(
    "mutate_trace",
    [
        lambda entry: entry.pop("tool_call_id"),
        lambda entry: entry.update(tool_name=1),
        lambda entry: entry.update(status="unknown"),
        lambda entry: entry.update(order="1"),
        lambda entry: entry.update(excerpt=1),
    ],
)
def test_malformed_trace_entry_is_a_schema_mismatch(mutate_trace) -> None:
    run = _run()
    run.metadata_json = copy.deepcopy(_metadata(run))
    [entry] = run.metadata_json[CODE_MODE_STATE_METADATA_KEY]["nested_trace"]
    mutate_trace(entry)

    with pytest.raises(CodeModeStateError) as exc_info:
        load_code_mode_state(run, snapshot_max_bytes=MAX_BYTES)

    assert exc_info.value.reason == "schema_mismatch"


def test_effect_ledger_append_is_bounded() -> None:
    effects = ()
    for index in range(25):
        effects = append_executed_effect(
            effects,
            nested_call_id=f"nested-{index}",
            tool_name="write",
            args_sha256=str(index),
        )
    with pytest.raises(ValueError, match="ledger exceeds"):
        append_executed_effect(
            effects, nested_call_id="overflow", tool_name="write", args_sha256="x"
        )


def test_clear_is_idempotent_and_preserves_unrelated_metadata() -> None:
    run = _run()
    run.metadata_json = _metadata(run)
    run.metadata_json = clear_code_mode_state_metadata(run)
    run.metadata_json = clear_code_mode_state_metadata(run)
    assert run.metadata_json == {"kept": True}


async def test_snapshot_failure_classification_distinguishes_worker_crash() -> None:
    assert classify_snapshot_load_failure(ValueError("bad")).reason == "snapshot_corrupt"
    async with AsyncMonty(request_timeout=0.05) as pool, pool.checkout() as session:
        with pytest.raises(MontyCrashedError) as exc_info:
            await session.feed_run("while True:\n    pass")
    assert classify_snapshot_load_failure(exc_info.value).reason == "resume_crash"
