"""Project validated direct and delegated saved proposals into reviewable leaves."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic_ai.messages import ToolCallPart
from pydantic_core import to_jsonable_python

from core.settings import settings
from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL, TERMINAL_RUN_STATUSES
from services.agent_runs.schemas import (
    AgentRunApprovalStateResponse,
    NestedTraceEntryRead,
    PendingDelegatedApprovalRead,
    PendingToolApprovalRead,
    PendingWorkflowStateRead,
    PendingWorkflowToolApprovalRead,
)
from services.agents.delegation_approval import DELEGATED_APPROVAL_KIND
from services.agents.runtime.approval_identity import (
    MAX_PROJECTION_LEAVES,
    approval_id,
    approval_revision,
    invalid_approval_state,
    proposal_digest,
)
from services.agents.runtime.approval_state import SuspendedRunState, load_suspended_run_state
from services.agents.runtime.code_mode.approval import code_mode_nested_call
from services.agents.runtime.code_mode.state import (
    CodeModeState,
    CodeModeStateError,
    load_code_mode_state,
)
from services.agents.runtime.delegation.tool_names import DELEGATE_TO_AGENT_TOOL_NAME
from services.agents.runtime.staged_tool_content import (
    tool_args_for_display,
    tool_replay_args_for_editing,
)


@dataclass(frozen=True)
class DirectApprovalNode:
    owner_run_id: UUID
    batch_id: UUID | None
    call: ToolCallPart
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class WorkflowApprovalNode:
    leaf: DirectApprovalNode
    outer_tool_call_id: str
    state: CodeModeState


ApprovalLeaf = DirectApprovalNode | WorkflowApprovalNode
ChildState = Literal["awaiting_approval", "missing", "invalid", "pending", "terminal"]


@dataclass(frozen=True)
class DelegatedApprovalNode:
    parent_tool_call_id: str
    child_run_id: UUID | None
    status: ChildState
    delegation: PendingDelegatedApprovalRead | None = None
    leaves: tuple[ApprovalLeaf, ...] = ()


@dataclass(frozen=True)
class ApprovalGraph:
    root_run_id: UUID
    conversation_id: UUID
    root_batch_id: UUID | None
    nodes: tuple[ApprovalLeaf | DelegatedApprovalNode, ...]


def delegated_child_id(metadata: Mapping[str, Any]) -> UUID | None:
    """Reads a declared child identity without treating malformed links as direct calls."""
    try:
        return UUID(str(metadata["child_run_id"]))
    except (KeyError, ValueError, TypeError):
        return None


def build_approval_graph(root: AgentRun, children: Mapping[UUID, AgentRun]) -> ApprovalGraph:
    """Builds one bounded graph from scoped rows without reads, writes, or execution."""
    if root.parent_run_id is not None or root.delegation_depth not in (None, 0):
        raise invalid_approval_state("Approval submissions require the root run")
    if root.status != RUN_STATUS_AWAITING_APPROVAL:
        raise invalid_approval_state("The root run is not awaiting approval")
    suspended = load_suspended_run_state(root)
    nodes: list[ApprovalLeaf | DelegatedApprovalNode] = []
    seen_children: set[UUID] = set()
    leaf_count = 0
    for call, metadata in _calls(suspended):
        if metadata.get("kind") != DELEGATED_APPROVAL_KIND:
            nodes.append(_leaf(root, suspended, call, metadata))
            leaf_count += 1
            continue
        node = _delegated_node(
            root, call, metadata, children, remaining=MAX_PROJECTION_LEAVES - leaf_count
        )
        if node.child_run_id in seen_children:
            raise invalid_approval_state("A delegated approval repeats a child run")
        if node.child_run_id is not None:
            seen_children.add(node.child_run_id)
        nodes.append(node)
        leaf_count += len(node.leaves)
    if (
        sum(len(node.leaves) if isinstance(node, DelegatedApprovalNode) else 1 for node in nodes)
        > MAX_PROJECTION_LEAVES
    ):
        raise invalid_approval_state("Saved approval graph has too many leaves")
    return ApprovalGraph(root.id, root.conversation_id, suspended.approval_batch_id, tuple(nodes))


def _calls(state: SuspendedRunState) -> list[tuple[ToolCallPart, Mapping[str, Any]]]:
    calls = state.deferred_tool_requests.approvals
    if len(calls) > MAX_PROJECTION_LEAVES:
        raise invalid_approval_state("Saved approval state has too many calls")
    if len({call.tool_call_id for call in calls}) != len(calls):
        raise invalid_approval_state("Saved approval calls have duplicate native identities")
    if not calls:
        raise invalid_approval_state("Saved approval state has no reviewable calls")
    result = []
    for call in calls:
        metadata = state.deferred_tool_requests.metadata.get(call.tool_call_id) or {}
        if (
            call.tool_name == DELEGATE_TO_AGENT_TOOL_NAME
            and metadata.get("kind") != DELEGATED_APPROVAL_KIND
        ):
            raise invalid_approval_state("Saved delegated approval metadata is missing or invalid")
        if call.tool_name == "run_workflow" and metadata.get("kind") != "code_mode":
            raise invalid_approval_state("Saved workflow approval metadata is missing or invalid")
        if "child_run_id" in metadata and metadata.get("kind") != DELEGATED_APPROVAL_KIND:
            raise invalid_approval_state("Saved delegated approval metadata is invalid")
        result.append((call, metadata))
    return result


def _leaf(
    run: AgentRun, suspended: SuspendedRunState, call: ToolCallPart, metadata: Mapping[str, Any]
) -> ApprovalLeaf:
    if metadata.get("kind") == DELEGATED_APPROVAL_KIND:
        raise invalid_approval_state("Nested delegation is not supported")
    nested = code_mode_nested_call(metadata)
    if metadata.get("kind") != "code_mode":
        return DirectApprovalNode(run.id, suspended.approval_batch_id, call, metadata)
    if nested is None or metadata.get("outer_tool_call_id") != call.tool_call_id:
        raise invalid_approval_state("Saved workflow approval metadata is invalid")
    try:
        state = load_code_mode_state(
            run,
            outer_tool_call_id=call.tool_call_id,
            snapshot_max_bytes=settings.AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES,
        )
    except (CodeModeStateError, KeyError, TypeError, ValueError) as exc:
        raise invalid_approval_state("Saved workflow state is invalid") from exc
    if state.nested_call_id != nested.tool_call_id:
        raise invalid_approval_state("Saved workflow leaf does not match its snapshot")
    _validate_pending_trace(state, nested)
    return WorkflowApprovalNode(
        DirectApprovalNode(run.id, suspended.approval_batch_id, nested, metadata),
        call.tool_call_id,
        state,
    )


def _validate_pending_trace(state: CodeModeState, nested: ToolCallPart) -> None:
    matches = [
        entry for entry in state.nested_trace if entry["tool_call_id"] == nested.tool_call_id
    ]
    if not matches and not state.trace_truncated:
        raise invalid_approval_state("Saved workflow trace has no pending approval")
    if len(matches) > 1:
        raise invalid_approval_state("Saved workflow trace repeats its pending approval")
    for entry in matches:
        if entry["status"] != "pending":
            raise invalid_approval_state("Saved workflow approval is already settled")
        if (
            entry["tool_name"] != nested.tool_name
            or entry["parent_tool_call_id"] != state.outer_tool_call_id
        ):
            raise invalid_approval_state("Saved workflow trace does not match its approval")
        args = nested.args_as_dict()
        if nested.tool_name == "write_file" and "content_ref" in args:
            continue
        if entry["args_sha256"] != proposal_digest(args):
            raise invalid_approval_state("Saved workflow arguments do not match its approval")


def _delegated_node(
    root: AgentRun,
    call: ToolCallPart,
    metadata: Mapping[str, Any],
    children: Mapping[UUID, AgentRun],
    *,
    remaining: int,
) -> DelegatedApprovalNode:
    child_id = delegated_child_id(metadata)
    if child_id is None or child_id == root.id:
        return DelegatedApprovalNode(call.tool_call_id, child_id, "invalid")
    child = children.get(child_id)
    if child is None or child.deleted:
        return DelegatedApprovalNode(call.tool_call_id, child_id, "missing")
    valid = (
        child.parent_run_id == root.id
        and child.workspace_id == root.workspace_id
        and child.user_id == root.user_id
        and child.delegation_depth == 1
        and str(child.agent_id) == metadata.get("child_agent_id")
        and str(child.conversation_id) == metadata.get("child_conversation_id")
    )
    if not valid:
        return DelegatedApprovalNode(call.tool_call_id, child_id, "invalid")
    if child.status in TERMINAL_RUN_STATUSES:
        return DelegatedApprovalNode(call.tool_call_id, child_id, "terminal")
    if child.status != RUN_STATUS_AWAITING_APPROVAL:
        return DelegatedApprovalNode(call.tool_call_id, child_id, "pending")
    suspended = load_suspended_run_state(child)
    child_calls = _calls(suspended)
    if len(child_calls) > remaining:
        raise invalid_approval_state("Saved approval graph has too many leaves")
    leaves = tuple(_leaf(child, suspended, leaf, meta) for leaf, meta in child_calls)
    delegation = PendingDelegatedApprovalRead(
        parent_tool_call_id=call.tool_call_id,
        child_agent_id=child.agent_id,
        child_agent_name=metadata.get("child_agent_name") or "Delegate agent",
        child_conversation_id=child.conversation_id,
        child_run_id=child.id,
        pending_approval_count=len(leaves),
    )
    return DelegatedApprovalNode(
        call.tool_call_id, child_id, "awaiting_approval", delegation, leaves
    )


def project_approval_graph(graph: ApprovalGraph) -> AgentRunApprovalStateResponse:
    """Returns the same safe proposal for stream and reload adapters."""
    approvals: list[PendingToolApprovalRead] = []
    workflows: list[PendingWorkflowStateRead] = []
    delegations: list[PendingDelegatedApprovalRead] = []
    fingerprints: list[dict[str, object]] = []
    for node in graph.nodes:
        delegation = None
        leaves = (node,)
        if isinstance(node, DelegatedApprovalNode):
            if node.status != "awaiting_approval" or node.delegation is None:
                raise invalid_approval_state(f"Delegated approval child is {node.status}")
            delegation = node.delegation
            delegations.append(delegation)
            leaves = node.leaves
        for leaf in leaves:
            pending, workflow, fingerprint = _project_leaf(graph.root_run_id, leaf, delegation)
            approvals.append(pending)
            fingerprints.append(fingerprint)
            if workflow is not None:
                workflows.append(workflow)
    revision = approval_revision(
        root_run_id=graph.root_run_id, root_batch_id=graph.root_batch_id, leaves=fingerprints
    )
    legacy = (
        workflows[0]
        if len(workflows) == 1 and workflows[0].owner_run_id == graph.root_run_id
        else None
    )
    response = AgentRunApprovalStateResponse(
        run_id=graph.root_run_id,
        conversation_id=graph.conversation_id,
        approvals=approvals,
        delegations=delegations,
        workflows=workflows,
        workflow=legacy,
        approval_revision=revision,
    )
    proposal_digest(response.model_dump(mode="json"))
    return response


def _project_leaf(
    root_run_id: UUID, node: ApprovalLeaf, delegation: PendingDelegatedApprovalRead | None
) -> tuple[PendingToolApprovalRead, PendingWorkflowStateRead | None, dict[str, object]]:
    leaf = node.leaf if isinstance(node, WorkflowApprovalNode) else node
    parent_id = node.outer_tool_call_id if isinstance(node, WorkflowApprovalNode) else None
    identity = approval_id(
        owner_run_id=leaf.owner_run_id,
        batch_id=leaf.batch_id,
        tool_call_id=leaf.call.tool_call_id,
        parent_tool_call_id=parent_id,
    )
    fields = {
        "approval_id": identity,
        "owner_run_id": leaf.owner_run_id,
        "root_run_id": root_run_id,
        "tool_call_id": leaf.call.tool_call_id,
        "name": leaf.call.tool_name,
        "args": to_jsonable_python(
            tool_args_for_display(
                tool_name=leaf.call.tool_name, args=leaf.call.args, metadata=leaf.metadata
            )
        ),
        "replay_args": to_jsonable_python(
            tool_replay_args_for_editing(
                tool_name=leaf.call.tool_name, args=leaf.call.args, metadata=leaf.metadata
            )
        ),
        "delegation": delegation,
        "derived_from_untrusted": leaf.metadata.get("derived_from_untrusted") is True,
        "taint_sources": _taint_sources(leaf.metadata),
    }
    pending = (
        PendingWorkflowToolApprovalRead(**fields, parent_tool_call_id=parent_id)
        if parent_id is not None
        else PendingToolApprovalRead(**fields)
    )
    if isinstance(node, WorkflowApprovalNode) and node.state.tainted:
        pending.derived_from_untrusted = True
        pending.taint_sources = [dict(source) for source in node.state.taint_sources]
        pending.taint_sources.extend(
            source
            for source in _taint_sources(leaf.metadata)
            if source not in pending.taint_sources
        )
    workflow = (
        _workflow(root_run_id, node, pending) if isinstance(node, WorkflowApprovalNode) else None
    )
    fingerprint = {
        "approval_id": identity,
        "owner_run_id": str(leaf.owner_run_id),
        "tool_call_id": leaf.call.tool_call_id,
        "parent_tool_call_id": parent_id,
        "delegation_call_id": delegation.parent_tool_call_id if delegation else None,
        "name": leaf.call.tool_name,
        "args_digest": proposal_digest(leaf.call.args_as_dict()),
        "presentation_digest": proposal_digest(fields["args"]),
        "taint_digest": proposal_digest(
            {
                "derived_from_untrusted": pending.derived_from_untrusted,
                "taint_sources": pending.taint_sources,
            }
        ),
        "workflow_digest": proposal_digest(node.state.code)
        if isinstance(node, WorkflowApprovalNode)
        else None,
    }
    return pending, workflow, fingerprint


def _workflow(
    root_run_id: UUID, node: WorkflowApprovalNode, pending: PendingWorkflowToolApprovalRead
) -> PendingWorkflowStateRead:
    return PendingWorkflowStateRead(
        owner_run_id=node.leaf.owner_run_id,
        root_run_id=root_run_id,
        delegation=pending.delegation,
        outer_tool_call_id=node.outer_tool_call_id,
        code=node.state.code,
        reason=node.state.reason,
        nested_trace=[
            NestedTraceEntryRead(
                tool_call_id=str(item["tool_call_id"]),
                tool_name=str(item["tool_name"]),
                summary=str(item.get("summary") or item["tool_name"]),
                status=item["status"],
                result_excerpt=item.get("excerpt"),
                position=int(item.get("order") or item.get("position") or 1),
                presentation_result=item.get("presentation_result"),
                started_at=item.get("started_at"),
                duration_ms=item.get("duration_ms"),
            )
            for item in node.state.nested_trace
        ],
        trace_truncated=node.state.trace_truncated,
        pending=pending,
    )


def _taint_sources(metadata: Mapping[str, Any]) -> list[dict[str, str]]:
    sources = metadata.get("taint_sources")
    if not isinstance(sources, list):
        return []
    return [
        {"source_kind": item["source_kind"], "source_ref": item["source_ref"]}
        for item in sources
        if isinstance(item, dict)
        and isinstance(item.get("source_kind"), str)
        and isinstance(item.get("source_ref"), str)
    ]
