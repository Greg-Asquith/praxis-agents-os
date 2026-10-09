# apps/api/services/integrations/entity_references.py

"""Published integration seam for provider-owned scoped entity references."""

from services.agents.runtime.entity_references.domain import (
    EntityChoice,
    EntityResolverPage,
    ScopedEntityReference,
)
from services.agents.runtime.entity_references.registry import EntityResolverDefinition
from services.agents.runtime.entity_references.service import (
    EntityResolverContext,
    resolve_runtime_references,
)

__all__ = [
    "EntityChoice",
    "EntityResolverContext",
    "EntityResolverDefinition",
    "EntityResolverPage",
    "ScopedEntityReference",
    "resolve_runtime_references",
]
