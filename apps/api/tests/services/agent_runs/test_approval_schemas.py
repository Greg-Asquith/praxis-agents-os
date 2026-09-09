"""Checks additive approval contracts without changing legacy payloads."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.agent_runs.schemas import (
    AgentRunApprovalStateResponse,
    AgentRunResumeRequest,
    PendingToolApprovalRead,
    PendingWorkflowToolApprovalRead,
)


def test_resume_accepts_both_identity_contracts_without_rewriting_native_ids() -> None:
    identity = uuid4()
    legacy = AgentRunResumeRequest.model_validate(
        {"decisions": [{"tool_call_id": "native-call", "decision": "approved"}]}
    )
    updated = AgentRunResumeRequest.model_validate(
        {
            "approval_revision": "a" * 64,
            "decisions": [
                {
                    "tool_call_id": "native-call",
                    "approval_id": str(identity),
                    "decision": "approved",
                    "override_args": {"message": "Edited"},
                }
            ],
        }
    )
    assert legacy.approval_revision is None
    assert updated.approval_revision == "a" * 64
    assert updated.decisions[0].approval_id == identity
    assert updated.decisions[0].tool_call_id == legacy.decisions[0].tool_call_id


@pytest.mark.parametrize("revision", ["", " ", "a b", "a" * 257, 42])
def test_resume_rejects_invalid_revision(revision: object) -> None:
    with pytest.raises(ValidationError):
        AgentRunResumeRequest.model_validate(
            {
                "approval_revision": revision,
                "decisions": [{"tool_call_id": "native-call", "decision": "approved"}],
            }
        )


def test_approval_identity_cannot_replace_native_id_during_transition() -> None:
    with pytest.raises(ValidationError):
        AgentRunResumeRequest.model_validate(
            {"decisions": [{"approval_id": str(uuid4()), "decision": "approved"}]}
        )


def test_legacy_response_omits_unset_identity_fields() -> None:
    response = AgentRunApprovalStateResponse(
        run_id=uuid4(),
        conversation_id=uuid4(),
        approvals=[PendingToolApprovalRead(tool_call_id="native", name="send", args={})],
    ).model_dump(mode="json")
    assert "approval_revision" not in response
    assert "workflows" not in response
    assert "approval_id" not in response["approvals"][0]
    assert "owner_run_id" not in response["approvals"][0]


def test_response_retains_nested_owner_and_parent_when_serialised_as_base_approval() -> None:
    owner, root, identity = uuid4(), uuid4(), uuid4()
    response = AgentRunApprovalStateResponse(
        run_id=root,
        conversation_id=uuid4(),
        approval_revision="a" * 64,
        approvals=[
            PendingWorkflowToolApprovalRead(
                tool_call_id="native",
                parent_tool_call_id="outer",
                owner_run_id=owner,
                root_run_id=root,
                approval_id=identity,
                name="send",
                args={},
            )
        ],
    ).model_dump(mode="json")
    assert response["approvals"][0]["parent_tool_call_id"] == "outer"
    assert response["approvals"][0]["owner_run_id"] == str(owner)
    assert response["approvals"][0]["approval_id"] == str(identity)
