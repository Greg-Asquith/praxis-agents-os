# apps/api/services/agent_runs/compile_approval_decisions.py

"""Compiles current approval leaves into bounded, owner-scoped SDK decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic_ai import DeferredToolResults, ToolApproved, ToolDenied
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.schemas import AgentRunResumeDecision, AgentRunResumeRequest
from services.agent_runs.utils import denial_message_for_model
from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args
from services.agents.delegation_approval import (
    DELEGATED_APPROVAL_CHILD_DEFERRED_TOOL_RESULTS_KEY,
)
from services.agents.runtime.approval_identity import (
    MAX_PROJECTION_LEAVES,
    approval_id,
    invalid_approval_state,
    proposal_digest,
)

if TYPE_CHECKING:
    from services.agents.runtime.approval_projection import ApprovalGraph, ApprovalLeaf

from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.code_mode.approval import build_code_mode_decision_metadata


async def compile_approval_decisions(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    graph: ApprovalGraph,
    runs: Mapping[UUID, AgentRun],
    payload: AgentRunResumeRequest,
) -> DeferredToolResults:
    """Validates every decision before returning executable results without run mutations."""
    from services.agents.runtime.approval_projection import (
        DelegatedApprovalNode,
        WorkflowApprovalNode,
        build_approval_graph,
        project_approval_graph,
    )

    root = runs.get(graph.root_run_id)
    if (
        root is None
        or root.user_id != actor.id
        or root.workspace_id != workspace.id
        or membership.user_id != actor.id
        or membership.workspace_id != workspace.id
    ):
        raise invalid_approval_state("Approval ownership is unavailable")
    current_graph = build_approval_graph(root, runs)
    projection = project_approval_graph(current_graph)
    if project_approval_graph(graph) != projection:
        raise _refresh_required()
    leaves = tuple(
        leaf
        for node in current_graph.nodes
        for leaf in (node.leaves if isinstance(node, DelegatedApprovalNode) else (node,))
    )
    decisions = _resolve_decisions(current_graph, leaves, payload)
    # Bound edits and nested results, including duplicated workflow decision metadata.
    proposal_digest(payload.model_dump(mode="json"))
    results_by_run: dict[UUID, DeferredToolResults] = {}
    for node in leaves:
        leaf = node.leaf if isinstance(node, WorkflowApprovalNode) else node
        owner = runs[leaf.owner_run_id]
        _validate_native_history(owner, node)
        result = results_by_run.setdefault(owner.id, DeferredToolResults())
        decision = decisions[_identity(node)]
        canonical = None
        if decision.decision == "approved":
            canonical = await validate_and_canonicalize_override_args(
                db,
                actor=actor,
                workspace=workspace,
                membership=membership,
                run=owner,
                tool_call=leaf.call,
                override_args=decision.override_args,
            )
        _add_leaf_result(result, node, decision, canonical)
    root_result = results_by_run.setdefault(root.id, DeferredToolResults())
    root_state = load_suspended_run_state(root)
    for node in current_graph.nodes:
        if not isinstance(node, DelegatedApprovalNode):
            continue
        if node.child_run_id is None:
            raise invalid_approval_state("Delegated approval ownership is unavailable")
        parent_call = next(
            call
            for call in root_state.deferred_tool_requests.approvals
            if call.tool_call_id == node.parent_tool_call_id
        )
        _validate_history_call(root, parent_call)
        root_result.approvals[node.parent_tool_call_id] = ToolApproved()
        root_result.metadata[node.parent_tool_call_id] = {
            **root_state.deferred_tool_requests.metadata[node.parent_tool_call_id],
            DELEGATED_APPROVAL_CHILD_DEFERRED_TOOL_RESULTS_KEY: to_jsonable_python(
                results_by_run[node.child_run_id]
            ),
        }
    proposal_digest(to_jsonable_python(root_result))
    return root_result


def _identity(node: ApprovalLeaf) -> str:
    from services.agents.runtime.approval_projection import WorkflowApprovalNode

    leaf = node.leaf if isinstance(node, WorkflowApprovalNode) else node
    return approval_id(
        owner_run_id=leaf.owner_run_id,
        batch_id=leaf.batch_id,
        tool_call_id=leaf.call.tool_call_id,
        parent_tool_call_id=node.outer_tool_call_id
        if isinstance(node, WorkflowApprovalNode)
        else None,
    )


def _resolve_decisions(
    graph: ApprovalGraph, leaves: tuple[ApprovalLeaf, ...], payload: AgentRunResumeRequest
) -> dict[str, AgentRunResumeDecision]:
    from services.agents.runtime.approval_projection import (
        WorkflowApprovalNode,
        project_approval_graph,
    )

    if len(payload.decisions) != len(leaves) or len(leaves) > MAX_PROJECTION_LEAVES:
        raise _refresh_required()
    projection = project_approval_graph(graph)
    legacy = payload.approval_revision is None and all(
        decision.approval_id is None for decision in payload.decisions
    )
    if legacy:
        if graph.root_batch_id is not None or any(
            isinstance(node, WorkflowApprovalNode) or node.batch_id is not None for node in leaves
        ):
            raise _refresh_required()
        native_ids = [node.call.tool_call_id for node in leaves]
        if len(set(native_ids)) != len(native_ids):
            raise _refresh_required()
        expected = {node.call.tool_call_id: _identity(node) for node in leaves}
        keys = [expected.get(decision.tool_call_id) for decision in payload.decisions]
    else:
        if payload.approval_revision != projection.approval_revision:
            raise _refresh_required()
        expected = {str(item.approval_id): item.tool_call_id for item in projection.approvals}
        keys = []
        for decision in payload.decisions:
            key = str(decision.approval_id)
            if expected.get(key) != decision.tool_call_id:
                raise _refresh_required()
            keys.append(key)
    if None in keys or len(set(keys)) != len(keys):
        raise _refresh_required()
    return {str(key): decision for key, decision in zip(keys, payload.decisions, strict=True)}


def _validate_native_history(run: AgentRun, node: ApprovalLeaf) -> None:
    from services.agents.runtime.approval_projection import WorkflowApprovalNode

    if isinstance(node, WorkflowApprovalNode):
        state = load_suspended_run_state(run)
        call = next(
            call
            for call in state.deferred_tool_requests.approvals
            if call.tool_call_id == node.outer_tool_call_id
        )
    else:
        call = node.call
    _validate_history_call(run, call)


def _validate_history_call(run: AgentRun, call: ToolCallPart) -> None:
    state = load_suspended_run_state(run)
    matches = [
        part
        for message in state.message_history
        for part in message.parts
        if isinstance(part, ToolCallPart | ToolReturnPart)
        and part.tool_call_id == call.tool_call_id
    ]
    if (
        len(matches) != 1
        or not isinstance(matches[0], ToolCallPart)
        or matches[0].tool_name != call.tool_name
        or proposal_digest(matches[0].args_as_dict()) != proposal_digest(call.args_as_dict())
    ):
        raise _refresh_required()


def _add_leaf_result(
    results: DeferredToolResults,
    node: ApprovalLeaf,
    decision: AgentRunResumeDecision,
    canonical: dict[str, object] | None,
) -> None:
    from services.agents.runtime.approval_projection import WorkflowApprovalNode
    from services.agents.runtime.dispatch import digest_args

    leaf = node.leaf if isinstance(node, WorkflowApprovalNode) else node
    if isinstance(node, WorkflowApprovalNode):
        effective = canonical if canonical is not None else leaf.call.args_as_dict()
        args_sha256, _ = digest_args(effective)
        results.approvals[node.outer_tool_call_id] = ToolApproved()
        results.metadata[node.outer_tool_call_id] = build_code_mode_decision_metadata(
            approval_metadata=leaf.metadata,
            decision=decision.decision,
            effective_args=effective,
            args_sha256=args_sha256,
            message=denial_message_for_model(decision.message)
            if decision.decision == "denied"
            else None,
            reason=decision.message if decision.decision == "denied" else None,
        )
    elif decision.decision == "approved":
        results.approvals[leaf.call.tool_call_id] = ToolApproved(override_args=canonical)
    else:
        results.approvals[leaf.call.tool_call_id] = ToolDenied(
            denial_message_for_model(decision.message)
        )
        results.metadata[leaf.call.tool_call_id] = {"reason": decision.message}


def _refresh_required() -> ConflictError:
    return ConflictError(
        "The pending approvals changed. Refresh the conversation before reviewing them.",
        conflicting_resource="agent_run",
        details={"error_code": "approval_refresh_required"},
    )
