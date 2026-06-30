# apps/api/services/agents/runtime/approval_state.py

"""Serialize and rehydrate suspended approval state for an agent run."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from pydantic_core import to_jsonable_python

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.conversation import Conversation

APPROVAL_STATE_METADATA_KEY = "approval_state"
APPROVAL_STATE_VERSION = 1

_DEFERRED_REQUESTS_ADAPTER = TypeAdapter(DeferredToolRequests)


@dataclass(frozen=True)
class SuspendedRunState:
    """Rehydratable state for a run waiting on tool approval."""

    message_history: list[ModelMessage]
    deferred_tool_requests: DeferredToolRequests
    pending_tool_call_ids: list[str]


def build_suspended_run_metadata(
    *,
    run: AgentRun,
    conversation: Conversation,
    message_history: Sequence[ModelMessage],
    deferred_tool_requests: DeferredToolRequests,
) -> dict[str, Any]:
    """Return run metadata with a fresh approval-state snapshot."""
    metadata = dict(run.metadata_json or {})
    metadata[APPROVAL_STATE_METADATA_KEY] = {
        "version": APPROVAL_STATE_VERSION,
        "run_id": str(run.id),
        "conversation_id": str(conversation.id),
        "agent_id": str(run.agent_id),
        "message_history": _dump_messages(message_history),
        "deferred_tool_requests": to_jsonable_python(deferred_tool_requests),
        "pending_tool_call_ids": pending_tool_call_ids(deferred_tool_requests),
    }
    return metadata


def clear_suspended_run_metadata(run: AgentRun) -> dict[str, Any] | None:
    """Return run metadata with approval state removed."""
    metadata = dict(run.metadata_json or {})
    metadata.pop(APPROVAL_STATE_METADATA_KEY, None)
    return metadata or None


def load_suspended_run_state(run: AgentRun) -> SuspendedRunState:
    """Load and validate the approval-state snapshot stored on an agent run."""
    raw = (run.metadata_json or {}).get(APPROVAL_STATE_METADATA_KEY)
    if not isinstance(raw, dict):
        raise ConflictError(
            "Agent run has no suspended approval state",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "run_status": run.status},
        )

    if raw.get("version") != APPROVAL_STATE_VERSION:
        raise ConflictError(
            "Agent run approval state version is not supported",
            conflicting_resource="agent_run",
            details={
                "run_id": str(run.id),
                "approval_state_version": str(raw.get("version")),
                "supported_version": str(APPROVAL_STATE_VERSION),
            },
        )

    if raw.get("run_id") != str(run.id):
        raise ConflictError(
            "Agent run approval state does not belong to this run",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "approval_state_run_id": str(raw.get("run_id"))},
        )
    if raw.get("conversation_id") != str(run.conversation_id):
        raise ConflictError(
            "Agent run approval state does not belong to this conversation",
            conflicting_resource="agent_run",
            details={
                "run_id": str(run.id),
                "conversation_id": str(run.conversation_id),
                "approval_state_conversation_id": str(raw.get("conversation_id")),
            },
        )
    if raw.get("agent_id") != str(run.agent_id):
        raise ConflictError(
            "Agent run approval state does not belong to this agent",
            conflicting_resource="agent_run",
            details={
                "run_id": str(run.id),
                "agent_id": str(run.agent_id),
                "approval_state_agent_id": str(raw.get("agent_id")),
            },
        )

    try:
        message_history = list(
            ModelMessagesTypeAdapter.validate_python(raw["message_history"])
        )
        deferred_tool_requests = _DEFERRED_REQUESTS_ADAPTER.validate_python(
            raw["deferred_tool_requests"]
        )
    except Exception as exc:
        raise ConflictError(
            "Agent run approval state cannot be rehydrated",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "error": exc.__class__.__name__},
        ) from exc

    pending_ids = pending_tool_call_ids(deferred_tool_requests)
    stored_pending_ids = raw.get("pending_tool_call_ids")
    if stored_pending_ids != pending_ids:
        raise ConflictError(
            "Agent run approval state pending tool ids are inconsistent",
            conflicting_resource="agent_run",
            details={
                "run_id": str(run.id),
                "pending_tool_call_ids": pending_ids,
                "stored_pending_tool_call_ids": stored_pending_ids,
            },
        )

    return SuspendedRunState(
        message_history=message_history,
        deferred_tool_requests=deferred_tool_requests,
        pending_tool_call_ids=pending_ids,
    )


def pending_tool_call_ids(requests: DeferredToolRequests) -> list[str]:
    """Return approval tool-call ids in stable order."""
    return [approval.tool_call_id for approval in requests.approvals]


def _dump_messages(messages: Sequence[ModelMessage]) -> list[dict[str, Any]]:
    return json.loads(ModelMessagesTypeAdapter.dump_json(list(messages)))
