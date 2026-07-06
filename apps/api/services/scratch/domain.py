# apps/api/services/scratch/domain.py

"""Domain values for agent scratch space."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from core.exceptions.general import AppValidationError

SCRATCH_NAME_MAX_LENGTH = 255


@dataclass(frozen=True)
class ScratchScope:
    """Exactly one scratch owner scope."""

    conversation_id: UUID | None = None
    run_id: UUID | None = None

    def __post_init__(self) -> None:
        if (self.conversation_id is None) == (self.run_id is None):
            raise AppValidationError(
                "Scratch scope must include exactly one owner",
                field="scope",
            )


class ScratchEntrySummary(BaseModel):
    """Content-free scratch entry listing."""

    name: str
    content_bytes: int
    updated_at: datetime
    expires_at: datetime


def validate_scratch_name(name: str) -> str:
    """Normalize and validate a model-chosen scratch entry name."""
    normalized = name.strip()
    if not normalized:
        raise AppValidationError("Scratch name cannot be blank", field="name")
    if len(normalized) > SCRATCH_NAME_MAX_LENGTH:
        raise AppValidationError(
            "Scratch name is too long",
            field="name",
            details={"max_length": SCRATCH_NAME_MAX_LENGTH},
        )
    return normalized
