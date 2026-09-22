# apps/api/services/agent_runs/review_approval.py

"""Retains a reviewed selection without changing the suspended model call."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from core.exceptions.general import ConflictError, NotFoundError
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.approval_expiry import approval_family_deadline
from services.agent_runs.load_approval_graph import load_approval_graph
from services.agent_runs.require_root_approval import require_root_approval
from services.agent_runs.schemas import AgentRunApprovalStateResponse, AgentRunReviewApprovalRequest
from services.agent_runs.settle_run_family import lock_run_family
from services.agent_runs.utils import approval_review_required, build_review_display_args
from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args
from services.agents.runtime.approval_identity import APPROVAL_REVISION_KEY, proposal_digest
from services.agents.runtime.approval_projection import (
    DelegatedApprovalNode,
    WorkflowApprovalNode,
    build_approval_graph,
    project_approval_graph,
)
from services.agents.runtime.approval_state import APPROVAL_STATE_METADATA_KEY
from services.agents.runtime.tools.registry import get_runtime_tool_definition
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    safe_record_operation_audit_event,
)


async def review_agent_run_approval(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    run_id: UUID,
    payload: AgentRunReviewApprovalRequest,
) -> AgentRunApprovalStateResponse:
    """Pins one exact pending leaf under the same family lock as approval acceptance."""
    root = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.workspace_id == workspace.id,
            AgentRun.user_id == actor.id,
            AgentRun.deleted.is_(False),
        )
    )
    if root is None or membership.user_id != actor.id or membership.workspace_id != workspace.id:
        raise NotFoundError("Agent run not found", resource_type="agent_run")
    await require_root_approval(db, run=root, actor=actor, workspace=workspace)
    family = await lock_run_family(db, run_id=root.id)
    deadline = approval_family_deadline(family)
    if deadline is not None and deadline <= datetime.now(UTC):
        raise ConflictError(
            "These approvals have expired.",
            conflicting_resource="agent_run",
            details={"code": "approval_expired"},
        )
    graph = await load_approval_graph(db, actor=actor, workspace=workspace, run_id=root.id)
    projection = project_approval_graph(graph)
    if payload.approval_revision != projection.approval_revision:
        raise ConflictError(
            "The pending approvals changed. Refresh the conversation.",
            conflicting_resource="agent_run",
            details={"error_code": "approval_refresh_required"},
        )
    leaves = [
        leaf
        for node in graph.nodes
        for leaf in (node.leaves if isinstance(node, DelegatedApprovalNode) else (node,))
    ]
    selected = next(
        (
            node
            for node, item in zip(leaves, projection.approvals, strict=True)
            if item.approval_id == payload.approval_id
        ),
        None,
    )
    if selected is None:
        raise approval_review_required()
    leaf = selected.leaf if isinstance(selected, WorkflowApprovalNode) else selected
    owner = next(run for run in family if run.id == leaf.owner_run_id)
    definition = get_runtime_tool_definition(leaf.call.tool_name)
    if (
        definition is None
        or not definition.approval_review_fields
        or definition.approval_display_args is None
    ):
        raise approval_review_required()
    proposal_digest(payload.model_dump(mode="json"))
    canonical = await validate_and_canonicalize_override_args(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        run=owner,
        tool_call=leaf.call,
        override_args=payload.override_args,
    )
    display = await build_review_display_args(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        run=owner,
        definition=definition,
        tool_call_id=leaf.call.tool_call_id,
        canonical=canonical,
    )
    proposal_digest(display)
    metadata_key = (
        selected.outer_tool_call_id
        if isinstance(selected, WorkflowApprovalNode)
        else leaf.call.tool_call_id
    )
    metadata = deepcopy(owner.metadata_json)
    state = metadata[APPROVAL_STATE_METADATA_KEY]
    state["deferred_tool_requests"]["metadata"][metadata_key] = {
        **leaf.metadata,
        "display_args": display,
        "reviewed_args": canonical,
    }
    owner.metadata_json = metadata
    updated = project_approval_graph(build_approval_graph(root, {run.id: run for run in family}))
    root_metadata = deepcopy(root.metadata_json)
    root_metadata[APPROVAL_STATE_METADATA_KEY][APPROVAL_REVISION_KEY] = updated.approval_revision
    root.metadata_json = root_metadata
    # Reviewing a selection preserves the original approval expiry deadline.
    for run in {root.id: root, owner.id: owner}.values():
        flag_modified(run, "updated_at")
    await safe_record_operation_audit_event(
        db,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.AGENT_RUN,
        resource_id=root.id,
        actor_type=AuditActorType.USER,
        actor_id=actor.id,
        requested_by_user_id=actor.id,
        details={
            "operation": "approval_reviewed",
            "approval_id": str(payload.approval_id),
            "approval_revision": updated.approval_revision,
            "owner_run_id": str(owner.id),
        },
    )
    await db.commit()
    return updated
