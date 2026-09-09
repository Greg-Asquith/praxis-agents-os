# apps/api/tests/support/approvals.py

"""Builds current approval submissions for deterministic runtime scenarios."""

from collections.abc import Sequence

from sqlalchemy import select

from models.agent_run import AgentRun
from services.agent_runs.compile_approval_decisions import compile_approval_decisions
from services.agent_runs.schemas import AgentRunResumeDecision, AgentRunResumeRequest
from services.agents.runtime.approval_projection import build_approval_graph, project_approval_graph


async def compile_scenario_decisions(db, *, actor, workspace, membership, run, decisions):
    """Submits opaque identities from the persisted root and child approval state."""
    children = await db.scalars(
        select(AgentRun).where(
            AgentRun.parent_run_id == run.id,
            AgentRun.workspace_id == workspace.id,
            AgentRun.user_id == actor.id,
        )
    )
    runs = {child.id: child for child in children}
    runs[run.id] = run
    graph = build_approval_graph(run, runs)
    return await compile_approval_decisions(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        graph=graph,
        runs=runs,
        payload=approval_submission(graph, decisions),
    )


def approval_submission(graph, decisions: Sequence[AgentRunResumeDecision]):
    """Adds current opaque identities to unambiguous scenario decisions."""
    projection = project_approval_graph(graph)
    submitted = []
    for decision in decisions:
        matches = [
            item for item in projection.approvals if item.tool_call_id == decision.tool_call_id
        ]
        identity = matches[0].approval_id if len(matches) == 1 else decision.approval_id
        submitted.append(decision.model_copy(update={"approval_id": identity}))
    return AgentRunResumeRequest(
        approval_revision=projection.approval_revision, decisions=submitted
    )
