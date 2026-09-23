# apps/api/services/agents/runtime/checkpoint_messages.py

"""Commits completed messages before execution advances to the next node."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai.messages import ModelMessage
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.domain import RUN_STATUS_RUNNING, RUN_TRIGGER_EVENT, RUN_TRIGGER_SCHEDULED
from services.agent_runs.record_usage import record_run_usage
from services.agent_runs.settle_run_family import lock_run_family
from services.agents.runtime.execution_control import ExecutionInterruptedError, InterruptionReason
from services.agents.runtime.persistence import persist_new_messages, unpersisted_messages


@dataclass
class MessageCheckpoint:
    """Tracks committed rows by their invocation-local SDK message index."""

    row_ids: list[UUID | None] = field(default_factory=list)

    @property
    def message_count(self) -> int:
        return len(self.row_ids)

    @property
    def row_count(self) -> int:
        return sum(row_id is not None for row_id in self.row_ids)


async def checkpoint_messages(
    db: AsyncSession,
    *,
    run: AgentRun,
    conversation: Conversation,
    owner_instance_id: str,
    messages: Sequence[ModelMessage],
    checkpoint: MessageCheckpoint,
    usage: RunUsage,
    skip_initial_user_prompt: bool,
    eager_tool_return_ids: set[str],
    client_message_id: str | None,
    tool_approval_metadata_by_call_id: Mapping[str, Mapping[str, Any]] | None,
) -> None:
    """Saves a completed suffix and advances its cursor only after commit."""
    from services.agents.runtime.run_persistence import usage_snapshot

    if len(messages) <= checkpoint.message_count:
        return
    family = await lock_run_family(db, run_id=run.id)
    if (
        run not in family
        or run.owner_instance_id != owner_instance_id
        or run.status != RUN_STATUS_RUNNING
    ):
        raise ExecutionInterruptedError(InterruptionReason.LEASE_LOST)
    row_ids: list[UUID | None] = []
    for index in range(checkpoint.message_count, len(messages)):
        pending = unpersisted_messages(
            messages[index : index + 1],
            skip_initial_user_prompt=skip_initial_user_prompt and index == 0,
            eager_tool_return_ids=eager_tool_return_ids,
        )
        rows = await persist_new_messages(
            db,
            conversation=conversation,
            run_id=run.id,
            messages=pending,
            client_message_id=client_message_id if index == 0 else None,
            tool_approval_metadata_by_call_id=tool_approval_metadata_by_call_id,
        )
        row_ids.append(rows[0].id if rows else None)
    if any(row_ids) and run.trigger in {RUN_TRIGGER_SCHEDULED, RUN_TRIGGER_EVENT}:
        conversation.unread = True
    await record_run_usage(db, run, usage_snapshot(usage))
    await db.commit()
    checkpoint.row_ids.extend(row_ids)
