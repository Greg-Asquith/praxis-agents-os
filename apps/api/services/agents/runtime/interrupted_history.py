# apps/api/services/agents/runtime/interrupted_history.py

"""Captures invocation-local history and bounds its durable retry payload."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse, ToolCallPart

from services.agents.runtime.approval_identity import MAX_PROPOSAL_BYTES
from services.agents.runtime.persistence import (
    close_dangling_tool_calls,
    without_initial_user_prompt,
    without_tool_returns,
)

INTERRUPTED_HISTORY_JOB_KIND = "agent_runs.persist_interrupted_history"
TRANSCRIPT_INVOCATION_KEY = "transcript_invocation_id"


@dataclass(frozen=True)
class InterruptedHistory:
    """Retains messages and approval evidence before execution state is cleared."""

    messages: Sequence[ModelMessage]
    skip_initial_user_prompt: bool = False
    eager_tool_return_ids: set[str] = field(default_factory=set)
    resumed_tool_calls: Sequence[ToolCallPart] = ()
    tool_approval_metadata_by_call_id: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def prepared_messages(self) -> list[ModelMessage]:
        messages = (
            without_initial_user_prompt(self.messages)
            if self.skip_initial_user_prompt
            else list(self.messages)
        )
        if self.resumed_tool_calls:
            messages = [ModelResponse(parts=list(self.resumed_tool_calls)), *messages]
        messages = close_dangling_tool_calls(messages, interrupted=True)
        if self.resumed_tool_calls:
            messages = messages[1:]
        # Eager returns already have durable rows, including declined approvals.
        return without_tool_returns(
            [message for message in messages if message.parts],
            tool_call_ids=self.eager_tool_return_ids,
        )


class InterruptedHistoryPayload(BaseModel):
    """Binds a bounded transcript suffix to one tenant and invocation."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    user_id: UUID
    conversation_id: UUID
    run_id: UUID
    invocation_id: str = Field(min_length=1, max_length=255)
    messages: list[dict[str, Any]]
    approval_metadata: dict[str, dict[str, Any]]
    omitted_messages: int = Field(default=0, ge=0)


def bounded_interrupted_history(
    history: InterruptedHistory,
    *,
    workspace_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    run_id: UUID,
    invocation_id: str,
) -> InterruptedHistoryPayload:
    """Keeps the latest contiguous message suffix within the proposal byte limit."""
    messages = json.loads(ModelMessagesTypeAdapter.dump_json(history.prepared_messages()))

    def candidate(start: int) -> InterruptedHistoryPayload:
        suffix = messages[start:]
        call_ids = {
            part.get("tool_call_id") for message in suffix for part in message.get("parts", [])
        }
        return InterruptedHistoryPayload(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            invocation_id=invocation_id,
            messages=suffix,
            approval_metadata={
                call_id: dict(value)
                for call_id, value in history.tool_approval_metadata_by_call_id.items()
                if call_id in call_ids
            },
            omitted_messages=start,
        )

    low, high = 0, len(messages)
    while low < high:
        middle = (low + high) // 2
        if interrupted_payload_size(candidate(middle)) > MAX_PROPOSAL_BYTES:
            low = middle + 1
        else:
            high = middle
    payload = candidate(low)
    if interrupted_payload_size(payload) > MAX_PROPOSAL_BYTES:
        raise ValueError("Interrupted history identity exceeds its payload limit")
    return payload


def interrupted_payload_size(payload: InterruptedHistoryPayload) -> int:
    """Measures canonical JSON bytes using the approval proposal encoding."""
    return len(json.dumps(payload.model_dump(mode="json"), separators=(",", ":")).encode())
