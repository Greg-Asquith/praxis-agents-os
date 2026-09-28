"""Checks additive approval contracts without changing legacy payloads."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.agent_runs.schemas import (
    AgentRunResumeRequest,
)


def test_approval_identity_cannot_replace_native_id_during_transition() -> None:
    with pytest.raises(ValidationError):
        AgentRunResumeRequest.model_validate(
            {"decisions": [{"approval_id": str(uuid4()), "decision": "approved"}]}
        )
