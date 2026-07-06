# apps/api/services/agents/runtime/delegation/approvals.py

"""Approval metadata helpers for delegated agent runs."""

from typing import Any
from uuid import UUID

from pydantic_ai import ApprovalRequired, DeferredToolRequests
from pydantic_core import to_jsonable_python

from models.agent import Agent
from services.agents.delegation_approval import (
    DELEGATED_APPROVAL_CHILD_AGENT_ID_KEY,
    DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY,
    DELEGATED_APPROVAL_CHILD_CONVERSATION_ID_KEY,
    DELEGATED_APPROVAL_CHILD_RUN_ID_KEY,
    DELEGATED_APPROVAL_KIND,
    DELEGATED_APPROVAL_KIND_KEY,
    DELEGATED_APPROVAL_PENDING_APPROVALS_KEY,
)
from services.agents.runtime.staged_tool_content import tool_args_for_display


def raise_delegate_approval_required(
    *,
    agent: Agent,
    run_id: UUID,
    conversation_id: UUID,
    deferred_tool_requests: DeferredToolRequests,
) -> None:
    raise ApprovalRequired(
        metadata={
            DELEGATED_APPROVAL_KIND_KEY: DELEGATED_APPROVAL_KIND,
            DELEGATED_APPROVAL_CHILD_AGENT_ID_KEY: str(agent.id),
            DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY: agent.name,
            DELEGATED_APPROVAL_CHILD_CONVERSATION_ID_KEY: str(conversation_id),
            DELEGATED_APPROVAL_CHILD_RUN_ID_KEY: str(run_id),
            DELEGATED_APPROVAL_PENDING_APPROVALS_KEY: pending_approval_descriptors(
                deferred_tool_requests
            ),
        }
    )


def pending_approval_descriptors(requests: DeferredToolRequests) -> list[dict[str, Any]]:
    return [
        {
            "tool_call_id": approval.tool_call_id,
            "name": approval.tool_name,
            "args": to_jsonable_python(
                tool_args_for_display(
                    tool_name=approval.tool_name,
                    args=approval.args,
                    metadata=requests.metadata.get(approval.tool_call_id),
                )
            ),
        }
        for approval in requests.approvals
    ]
