# apps/api/services/agents/runtime/subagents/spec.py

"""The persisted definition of one sub-agent run."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.agents.runtime.subagents.constants import (
    SUBAGENT_INSTRUCTIONS_MAX_LENGTH,
    SUBAGENT_METADATA_KEY,
    SUBAGENT_ROLE_MAX_LENGTH,
)


class SubagentSpec(BaseModel):
    """Stored in the child run's metadata so approval resume rebuilds the same sub-agent."""

    role: str = Field(min_length=1, max_length=SUBAGENT_ROLE_MAX_LENGTH)
    instructions: str = Field(min_length=1, max_length=SUBAGENT_INSTRUCTIONS_MAX_LENGTH)
    model_provider: str
    model: str

    model_config = ConfigDict(extra="ignore", frozen=True)


def subagent_spec_from_metadata(metadata: Any) -> SubagentSpec | None:
    """Return the sub-agent spec from run or agent metadata, or None for a normal agent."""
    if not isinstance(metadata, dict) or SUBAGENT_METADATA_KEY not in metadata:
        return None
    try:
        return SubagentSpec.model_validate(metadata[SUBAGENT_METADATA_KEY])
    except ValidationError as exc:
        raise ValueError("Saved sub-agent metadata is invalid") from exc
