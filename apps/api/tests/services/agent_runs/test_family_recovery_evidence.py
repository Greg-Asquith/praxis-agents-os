# apps/api/tests/services/agent_runs/test_family_recovery_evidence.py

"""Checks truthful action evidence across denial and terminal family settlement."""

from uuid import uuid4

import pytest
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolApproved, ToolDenied
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_core import to_jsonable_python

from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.build_family_recovery_evidence import build_family_recovery_evidence
from services.agent_runs.continuation_state import ApprovalContinuation, store_approval_continuation
from services.agent_runs.settle_run_family import settle_run_family
from services.agents.runtime.approval_state import (
    build_suspended_run_metadata,
    load_suspended_run_state,
)
from services.agents.runtime.code_mode.approval import (
    build_code_mode_approval_metadata,
    build_code_mode_decision_metadata,
)
from tests.support.scenario import build_scenario_agent

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def recovery_family(committed_db_session_factory):
    context = await build_scenario_agent(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        conversation = Conversation(
            user_id=root.user_id,
            workspace_id=root.workspace_id,
            created_by=root.user_id,
            active_agent_id=root.agent_id,
        )
        db.add(conversation)
        await db.flush()
        child = AgentRun(
            conversation_id=conversation.id,
            agent_id=root.agent_id,
            workspace_id=root.workspace_id,
            user_id=root.user_id,
            parent_run_id=root.id,
            delegation_depth=1,
            trigger="delegated",
            status="running",
        )
        db.add(child)
        await db.flush()
        for run in (root, child):
            conversation = await db.get(Conversation, run.conversation_id)
            direct = ToolCallPart("write_file", {"content": "private"}, "denied-direct")
            nested = ToolCallPart("write_file", {"content": "private"}, "denied-workflow")
            outer = ToolCallPart("run_workflow", {"code": "private"}, "outer")
            approved = ToolCallPart("write_file", {"content": "private"}, "approved")
            metadata = {
                "outer": build_code_mode_approval_metadata(
                    outer_tool_call_id="outer", nested_call=nested, reason=None
                )
            }
            calls = [direct, outer, approved]
            run.metadata_json = build_suspended_run_metadata(
                run=run,
                conversation=conversation,
                message_history=[ModelResponse(parts=calls)],
                deferred_tool_requests=DeferredToolRequests(approvals=calls, metadata=metadata),
            )
            run.status = "running"
        root_results = DeferredToolResults()
        for run in (root, child):
            state = load_suspended_run_state(run)
            results = DeferredToolResults(
                approvals={
                    "denied-direct": ToolDenied("Do not write"),
                    "outer": ToolApproved(),
                    "approved": ToolApproved(),
                },
                metadata={
                    "outer": build_code_mode_decision_metadata(
                        approval_metadata=state.deferred_tool_requests.metadata["outer"],
                        decision="denied",
                        effective_args={"content": "private"},
                        args_sha256="a" * 64,
                        message="Do not write",
                    )
                },
            )
            if run.id == root.id:
                root_results = results
            else:
                root_results.metadata["delegate"] = {
                    "child_run_id": str(child.id),
                    "child_deferred_tool_results": to_jsonable_python(results),
                }
        store_approval_continuation(
            root,
            ApprovalContinuation(
                generation=uuid4(),
                owner_instance_id=uuid4(),
                approval_revision="a" * 64,
                request_digest="b" * 64,
                child_batches={child.id: load_suspended_run_state(child).approval_batch_id},
                deferred_tool_results=to_jsonable_python(root_results),
                phase="started",
            ),
        )
        await db.flush()
        yield db, root, child


async def test_recovery_excludes_denied_direct_and_workflow_actions(recovery_family):
    db, root, child = recovery_family
    evidence = await build_family_recovery_evidence(db, family=[root, child])
    assert {
        (action["owner_run_id"], action["tool_call_id"], action["status"])
        for action in evidence["recovery"]["actions"]
    } == {(str(run.id), "approved", "uncertain") for run in (root, child)}
    assert "private" not in str(evidence)


async def test_old_child_denials_do_not_hide_a_fresh_batch(recovery_family):
    db, root, child = recovery_family
    metadata = dict(child.metadata_json)
    metadata["approval_state"] = {
        **metadata["approval_state"],
        "approval_batch_id": str(uuid4()),
    }
    child.metadata_json = metadata
    evidence = await build_family_recovery_evidence(db, family=[root, child])
    assert {
        action["tool_call_id"]
        for action in evidence["recovery"]["actions"]
        if action["owner_run_id"] == str(child.id)
    } == {"approved", "denied-direct", "denied-workflow"}


async def test_standalone_workflow_recovery_keeps_its_existing_contract(recovery_family):
    from services.agents.runtime.run_persistence import persist_failed_run

    db, root, _child = recovery_family
    root.metadata_json = {
        key: value for key, value in root.metadata_json.items() if key != "approval_continuation"
    }
    await db.flush()
    completion = {
        "error_code": "code_mode_resume_requires_recovery",
        "executed_effects": [{"nested_call_id": "earlier", "tool_name": "write_file"}],
    }
    await persist_failed_run(
        db,
        run_id=root.id,
        error_code="code_mode_resume_requires_recovery",
        error_message="Review the completed actions.",
        completion_json=completion,
    )
    assert root.error_code == "code_mode_resume_requires_recovery"
    assert root.outcome == "blocked"
    assert root.completion_json == completion


async def test_child_budget_failure_retains_recovery_for_root_settlement(recovery_family):
    from services.agents.runtime.run_persistence import persist_failed_run

    db, root, child = recovery_family
    child.metadata_json = {
        **child.metadata_json,
        "code_mode_state": {
            "run_id": str(child.id),
            "snapshot_b64": "private interpreter state",
            "executed_effects": [{"nested_call_id": "completed", "tool_name": "write_file"}],
        },
    }
    await db.flush()
    budget = {"kind": "requests", "limit": 4}
    await persist_failed_run(
        db,
        run_id=child.id,
        error_code="usage_limit_exceeded",
        error_message="The specialist reached its request budget.",
        completion_json={"error_code": "usage_limit_exceeded", "tripped_budget": budget},
    )
    await db.refresh(child)
    assert child.error_code == "usage_limit_exceeded"
    assert child.outcome == "budget_exhausted"
    assert child.completion_json["tripped_budget"] == budget
    assert child.completion_json["recovery"]["actions"]
    assert "code_mode_state" not in (child.metadata_json or {})
    await settle_run_family(db, run_id=root.id)
    await db.commit()
    await db.refresh(root)
    actions = root.completion_json["recovery"]["actions"]
    assert {
        (action["tool_call_id"], action["status"])
        for action in actions
        if action["owner_run_id"] == str(child.id)
    } == {("completed", "completed"), ("approved", "uncertain")}
    assert "private" not in str(root.completion_json)
    assert root.outcome == "blocked"


@pytest.mark.parametrize("status", ["cancelled", "failed"])
@pytest.mark.parametrize("settle_child_first", [False, True])
async def test_terminal_family_retains_completed_and_uncertain_effects(
    recovery_family, status, settle_child_first
):
    db, root, child = recovery_family
    child.metadata_json = {
        **child.metadata_json,
        "code_mode_state": {
            "run_id": str(child.id),
            "snapshot_b64": "private",
            "executed_effects": [
                {"nested_call_id": "completed", "tool_name": "write_file"},
            ],
        },
    }
    await db.flush()
    if settle_child_first:
        await settle_run_family(db, run_id=child.id, status=status)
        assert "code_mode_state" not in (child.metadata_json or {})
    await settle_run_family(db, run_id=root.id, status=status)
    await db.commit()
    await db.refresh(root)
    assert root.status == status
    assert root.outcome == ("cancelled" if status == "cancelled" else "blocked")
    if status == "cancelled":
        assert root.error_code is None
    actions = root.completion_json["recovery"]["actions"]
    assert {action["tool_call_id"] for action in actions} == {"completed", "approved"}
    assert next(action for action in actions if action["tool_call_id"] == "completed") == {
        "owner_run_id": str(child.id),
        "tool_call_id": "completed",
        "tool_name": "write_file",
        "status": "completed",
    }
    assert "private" not in str(root.completion_json)
    assert "approval_continuation" not in (root.metadata_json or {})
    assert "approval_state" not in (child.metadata_json or {})
