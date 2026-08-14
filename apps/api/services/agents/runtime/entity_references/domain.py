# apps/api/services/agents/runtime/entity_references/domain.py

"""Typed values shared by entity selectors and runtime tools."""

from dataclasses import dataclass
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ENTITY_REFERENCE_VERSION = 1


class EntityReference(BaseModel):
    """Versioned server-resolved reference persisted in tool arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = ENTITY_REFERENCE_VERSION
    entity_kind: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=1000)
    scope_label: str | None = Field(default=None, max_length=500)

    identity_fields: ClassVar[tuple[str, ...]] = ("version", "entity_kind")

    def identity(self) -> tuple[str, ...]:
        """Return the stable, non-display identity used to match hydration results."""
        values = self.model_dump(mode="json")
        return tuple(str(values[field]) for field in self.identity_fields)


class InternalEntityReference(EntityReference):
    """Reference to a workspace-owned row."""

    entity_id: UUID

    identity_fields: ClassVar[tuple[str, ...]] = (
        *EntityReference.identity_fields,
        "entity_id",
    )


class ScopedEntityReference(EntityReference):
    """Provider-owned entity reference resolved against active context at use time."""

    @property
    def provider_scope_id(self) -> str:
        """Return the provider-owned resource scope used for authorization lookup."""
        raise NotImplementedError

    @property
    def provider_entity_id(self) -> str:
        """Return the provider-owned entity identifier used for exact hydration."""
        raise NotImplementedError


class AgentReference(InternalEntityReference):
    entity_kind: Literal["agent"] = "agent"


class MemoryReference(InternalEntityReference):
    entity_kind: Literal["memory"] = "memory"


class ArtifactReference(InternalEntityReference):
    entity_kind: Literal["artifact"] = "artifact"


class KnowledgeDocumentReference(InternalEntityReference):
    entity_kind: Literal["knowledge_document"] = "knowledge_document"


class FileReference(InternalEntityReference):
    entity_kind: Literal["file"] = "file"


class EntityChoice(BaseModel):
    """Provider-neutral option returned to the browser."""

    model_config = ConfigDict(extra="forbid")

    identity: tuple[str, ...]
    value: dict[str, Any]
    label: str
    description: str | None = None
    scope_label: str | None = None
    icon: str | None = None

    @classmethod
    def from_reference(
        cls, reference: EntityReference, *, icon: str | None = None
    ) -> "EntityChoice":
        return cls(
            identity=reference.identity(),
            value=reference.model_dump(mode="json"),
            label=reference.label,
            description=reference.description,
            scope_label=reference.scope_label,
            icon=icon,
        )


@dataclass(frozen=True)
class EntityResolverPage:
    choices: tuple[EntityChoice, ...]
    next_cursor: str | None = None


def internal_entity_id(value: InternalEntityReference | UUID | str) -> UUID:
    """Normalize trusted in-process calls while public tool schemas stay structured."""
    return value.entity_id if isinstance(value, InternalEntityReference) else UUID(str(value))
