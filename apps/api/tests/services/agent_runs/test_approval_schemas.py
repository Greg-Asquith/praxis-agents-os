"""Checks resume decisions keep the native tool call ID beside the approval ID."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.agent_runs.schemas import (
    AgentRunResumeRequest,
)


def test_approval_identity_cannot_replace_native_id() -> None:
    with pytest.raises(ValidationError):
        AgentRunResumeRequest.model_validate(
            {
                "approval_revision": "0" * 64,
                "decisions": [{"approval_id": str(uuid4()), "decision": "approved"}],
            }
        )
