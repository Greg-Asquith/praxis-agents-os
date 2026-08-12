# apps/api/services/status/get_summary.py

"""Compute an exact actor-visible status summary for one workspace."""

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import AgentSchedule
from models.agent_run import AgentRun
from models.conversation import CONVERSATION_SOURCE_DELEGATED, Conversation
from models.user import User
from models.workspace import Workspace
from services.agent_runs.domain import (
    RUN_OUTCOME_BUDGET_EXHAUSTED,
    RUN_OUTCOME_GATE_FAILED,
    RUN_STATUS_AWAITING_APPROVAL,
)
from services.agent_schedules.runs import (
    RUN_STATUS_RETRYABLE_FAILED,
    RUN_STATUS_TERMINAL_FAILED,
)
from services.agent_schedules.utils import latest_schedule_run_subquery
from services.status.schemas import StatusSummary

SCHEDULE_ATTENTION_STATUSES = frozenset({RUN_STATUS_RETRYABLE_FAILED, RUN_STATUS_TERMINAL_FAILED})
SCHEDULE_ATTENTION_OUTCOMES = frozenset({RUN_OUTCOME_GATE_FAILED, RUN_OUTCOME_BUDGET_EXHAUSTED})


async def get_status_summary(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
) -> StatusSummary:
    """Return pagination-independent counts for the authenticated workspace member."""

    active_approval_exists = exists(
        select(AgentRun.id).where(
            AgentRun.conversation_id == Conversation.id,
            AgentRun.workspace_id == workspace.id,
            AgentRun.user_id == actor.id,
            AgentRun.status == RUN_STATUS_AWAITING_APPROVAL,
            AgentRun.deleted == False,  # noqa: E712
        )
    )
    unread_conversations = (
        select(func.count())
        .select_from(Conversation)
        .where(
            Conversation.workspace_id == workspace.id,
            Conversation.user_id == actor.id,
            Conversation.deleted == False,  # noqa: E712
            Conversation.source != CONVERSATION_SOURCE_DELEGATED,
            Conversation.unread.is_(True),
            ~active_approval_exists,
        )
        .scalar_subquery()
    )
    conversations_needing_approval = (
        select(func.count())
        .select_from(AgentRun)
        .where(
            AgentRun.workspace_id == workspace.id,
            AgentRun.user_id == actor.id,
            AgentRun.status == RUN_STATUS_AWAITING_APPROVAL,
            AgentRun.parent_run_id.is_(None),
            AgentRun.deleted == False,  # noqa: E712
        )
        .scalar_subquery()
    )

    latest_schedule_runs = latest_schedule_run_subquery(workspace_id=workspace.id)
    schedules_needing_attention = (
        select(func.count())
        .select_from(AgentSchedule)
        .join(
            latest_schedule_runs,
            latest_schedule_runs.c.schedule_id == AgentSchedule.id,
        )
        .outerjoin(AgentRun, AgentRun.id == latest_schedule_runs.c.agent_run_id)
        .where(
            AgentSchedule.workspace_id == workspace.id,
            AgentSchedule.deleted == False,  # noqa: E712
            # Keep this set aligned with schedule_health_from_run(): both retry
            # states shown by the status summary plus terminal
            # completion-contract failures.
            or_(
                latest_schedule_runs.c.status.in_(SCHEDULE_ATTENTION_STATUSES),
                AgentRun.outcome.in_(SCHEDULE_ATTENTION_OUTCOMES),
            ),
        )
        .scalar_subquery()
    )

    row = (
        await db.execute(
            select(
                unread_conversations.label("unread_conversations"),
                conversations_needing_approval.label("conversations_needing_approval"),
                schedules_needing_attention.label("schedules_needing_attention"),
            )
        )
    ).one()
    return StatusSummary.model_validate(row._mapping)
