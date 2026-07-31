# apps/api/services/agents/runtime/entity_references/registry.py

"""Entity resolver contribution contract and singular registry."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter

from services.agents.runtime.entity_references.domain import (
    EntityChoice,
    EntityReference,
    EntityResolverPage,
)

if False:  # pragma: no cover - typing-only import without runtime cycles
    from services.agents.runtime.entity_references.service import EntityResolverContext

SearchEntityReferencesFn = Callable[
    ["EntityResolverContext", str, Mapping[str, Any], int, str | None],
    Awaitable[EntityResolverPage],
]
ResolveEntityReferencesFn = Callable[
    ["EntityResolverContext", Sequence[Any], Mapping[str, Any]],
    Awaitable[Sequence[EntityChoice]],
]


@dataclass(frozen=True)
class EntityResolverDefinition:
    """One authorized entity-kind lookup implementation."""

    entity_kind: str
    reference_type: type[EntityReference]
    search: SearchEntityReferencesFn
    resolve: ResolveEntityReferencesFn
    max_page_size: int = 25
    requires_active_context: bool = False
    provider_key: str | None = None

    def reference_adapter(self) -> TypeAdapter[EntityReference]:
        return TypeAdapter(self.reference_type)


ENTITY_RESOLVERS: dict[str, EntityResolverDefinition] = {}


def register_entity_resolver(definition: EntityResolverDefinition) -> None:
    if not definition.entity_kind or not definition.entity_kind.replace("_", "a").isalnum():
        raise RuntimeError("Entity resolver kind must be lowercase snake_case")
    if definition.max_page_size < 1 or definition.max_page_size > 100:
        raise RuntimeError("Entity resolver max page size must be between 1 and 100")
    if not issubclass(definition.reference_type, EntityReference):
        raise TypeError("Entity resolver reference type must extend EntityReference")
    declared_kind = definition.reference_type.model_fields["entity_kind"].default
    if declared_kind != definition.entity_kind:
        raise RuntimeError("Entity resolver kind must match its structured reference type")
    if definition.entity_kind in ENTITY_RESOLVERS:
        raise RuntimeError(f"Duplicate entity resolver kind: {definition.entity_kind}")
    ENTITY_RESOLVERS[definition.entity_kind] = definition


def get_entity_resolver(entity_kind: str) -> EntityResolverDefinition | None:
    return ENTITY_RESOLVERS.get(entity_kind)
