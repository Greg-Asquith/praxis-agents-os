# apps/api/services/agents/runtime/entity_references/__init__.py

"""Human-readable, server-authorized runtime tool entity references."""

from services.agents.runtime.entity_references.domain import (
    AgentReference,
    ArtifactReference,
    EntityChoice,
    EntityReference,
    EntityResolverPage,
    FileReference,
    InternalEntityReference,
    KnowledgeDocumentReference,
    MemoryReference,
    ScopedEntityReference,
)
from services.agents.runtime.entity_references.registry import (
    EntityResolverDefinition,
    get_entity_resolver,
    register_entity_resolver,
)

__all__ = [
    "AgentReference",
    "ArtifactReference",
    "EntityChoice",
    "EntityReference",
    "EntityResolverDefinition",
    "EntityResolverPage",
    "FileReference",
    "InternalEntityReference",
    "KnowledgeDocumentReference",
    "MemoryReference",
    "ScopedEntityReference",
    "get_entity_resolver",
    "register_entity_resolver",
]
