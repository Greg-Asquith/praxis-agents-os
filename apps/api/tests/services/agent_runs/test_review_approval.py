"""Checks retained review isolation across delegated native and workflow leaves."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.exceptions.general import AppValidationError, ConflictError
from integrations.sharepoint.tools.write_file import DEFINITION
from models.agent import Agent
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.review_approval import review_agent_run_approval
from services.agent_runs.schemas import (
    AgentRunResumeDecision,
    AgentRunResumeRequest,
    AgentRunReviewApprovalRequest,
)
from services.agents.runtime.approval_projection import build_approval_graph, project_approval_graph
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.context.domain import EMPTY_ACTIVE_CONTEXT
from tests.services.agent_runs.test_compile_approval_decisions import compile_for, family


@pytest.mark.parametrize("workflow", [False, True])
async def test_review_one_delegated_leaf_preserves_sibling_and_replays_selection(
    monkeypatch, workflow
):
    root, runs = family(workflow=workflow)
    for run in runs.values():
        run.trigger = "interactive"
        run.updated_at = datetime.now(UTC)
    child = next(run for run in runs.values() if run.id != root.id)
    source = FileReference(entity_id=uuid4(), label="Chosen File").model_dump(mode="json")
    canonical = {"value": 9, "source": source}
    display = canonical | {"_source": {"file_id": source["entity_id"], "revision_id": str(uuid4())}}
    definition = replace(
        DEFINITION,
        name="update",
        approval_input_model=None,
        approval_display_args=AsyncMock(return_value=display),
    )
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, "update", definition)
    module = "services.agent_runs.review_approval"
    monkeypatch.setattr(f"{module}.require_root_approval", AsyncMock())
    monkeypatch.setattr(f"{module}.lock_run_family", AsyncMock(return_value=list(runs.values())))
    monkeypatch.setattr(
        f"{module}.load_approval_graph",
        AsyncMock(side_effect=lambda *a, **k: build_approval_graph(root, runs)),
    )
    monkeypatch.setattr(
        f"{module}.validate_and_canonicalize_override_args", AsyncMock(return_value=canonical)
    )
    monkeypatch.setattr(f"{module}.safe_record_operation_audit_event", AsyncMock())
    authorizer = AsyncMock(
        return_value=SimpleNamespace(
            context=SimpleNamespace(
                conversation=Conversation(id=child.conversation_id),
                agent=Agent(id=child.agent_id),
                active_context=EMPTY_ACTIVE_CONTEXT,
            )
        )
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field", authorizer
    )
    actor, workspace = User(id=root.user_id), Workspace(id=root.workspace_id)
    membership = WorkspaceMembership(user_id=actor.id, workspace_id=workspace.id)
    graph = build_approval_graph(root, runs)
    projection = project_approval_graph(graph)
    item = next(item for item in projection.approvals if item.owner_run_id == child.id)
    payload = AgentRunReviewApprovalRequest(
        approval_id=item.approval_id,
        approval_revision=projection.approval_revision,
        override_args=canonical,
    )
    before = {key: deepcopy(run.metadata_json) for key, run in runs.items()}
    db = AsyncMock()
    db.scalar.return_value = root
    updated = await review_agent_run_approval(
        db, actor=actor, workspace=workspace, membership=membership, run_id=root.id, payload=payload
    )
    assert authorizer.await_args.kwargs["run"].id == child.id
    assert updated.approval_revision != projection.approval_revision
    assert (
        next(item for item in updated.approvals if item.owner_run_id == child.id).replay_args
        == canonical
    )
    assert (
        child.metadata_json["approval_state"]["message_history"]
        == before[child.id]["approval_state"]["message_history"]
    )
    assert child.metadata_json.get("code_mode_state") == before[child.id].get("code_mode_state")
    sibling = next(run for run in runs.values() if run.id not in {root.id, child.id})
    assert sibling.metadata_json == before[sibling.id]
    monkeypatch.setattr(
        "services.agent_runs.compile_approval_decisions.validate_and_canonicalize_override_args",
        AsyncMock(side_effect=lambda *a, **k: k["override_args"]),
    )
    decisions = AgentRunResumeRequest(
        approval_revision=updated.approval_revision,
        decisions=[
            AgentRunResumeDecision(
                tool_call_id=entry.tool_call_id,
                approval_id=entry.approval_id,
                decision="approved" if entry.approval_id == item.approval_id else "denied",
            )
            for entry in updated.approvals
        ],
    )
    result = await compile_for(root, runs, decisions)
    child_result = result.metadata["delegate-0"]["child_deferred_tool_results"]
    effective = (
        child_result["metadata"]["outer"]["code_mode_decision"]["effective_args"]
        if workflow
        else child_result["approvals"]["same"]["override_args"]
    )
    assert effective == canonical
    with pytest.raises(ConflictError):
        await review_agent_run_approval(
            db,
            actor=actor,
            workspace=workspace,
            membership=membership,
            run_id=root.id,
            payload=payload,
        )
    root.updated_at = datetime.now(UTC) - timedelta(days=365)
    with pytest.raises(ConflictError, match="expired"):
        await review_agent_run_approval(
            db,
            actor=actor,
            workspace=workspace,
            membership=membership,
            run_id=root.id,
            payload=payload.model_copy(update={"approval_revision": updated.approval_revision}),
        )


@pytest.mark.parametrize(
    "content, source",
    [(None, None), ("Text", {"entity_id": str(uuid4()), "label": "File", "entity_type": "file"})],
)
async def test_content_source_exclusivity_checked_before_entity_resolution(
    monkeypatch, content, source
):
    from pydantic_ai.messages import ToolCallPart

    from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args

    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, DEFINITION.name, DEFINITION)
    resolver = AsyncMock()
    monkeypatch.setattr(
        "services.agent_runs.validate_override_args._canonicalize_entity_fields", resolver
    )
    call = ToolCallPart(DEFINITION.name, {"name": "note.txt", "content": "Original"}, "write")
    with pytest.raises(AppValidationError):
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=None,
            workspace=None,
            membership=None,
            run=None,
            tool_call=call,
            override_args={"name": "note.txt", "content": content, "source": source},
        )
    resolver.assert_not_awaited()
