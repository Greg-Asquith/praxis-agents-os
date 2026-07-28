# apps/api/services/files/revision_actor.py

"""Actor provenance shared by file revision writers."""

from dataclasses import dataclass
from uuid import UUID

from core.exceptions.general import AppValidationError


@dataclass(frozen=True)
class FileRevisionActor:
    """Exactly one actor for an immutable file revision."""

    user_id: UUID | None = None
    agent_id: UUID | None = None
    system: bool = False

    def validate(self) -> None:
        if sum((self.user_id is not None, self.agent_id is not None, self.system)) != 1:
            raise AppValidationError("A file revision requires exactly one actor")

    def columns(self) -> dict[str, UUID | bool | None]:
        self.validate()
        return {
            "created_by_user_id": self.user_id,
            "created_by_agent_id": self.agent_id,
            "created_by_system": self.system,
        }
