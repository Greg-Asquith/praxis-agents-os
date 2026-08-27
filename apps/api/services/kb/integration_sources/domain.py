# apps/api/services/kb/integration_sources/domain.py

"""Knowledge Base integration source value objects."""

from dataclasses import dataclass

from models.integrations import IntegrationConnection, IntegrationResource
from services.integrations.plugin import IntegrationKnowledgeSourceDefinition


@dataclass(frozen=True)
class AuthorizedIntegrationKnowledgeSource:
    """One actor-owned resource and its provider source operations."""

    connection: IntegrationConnection
    resource: IntegrationResource
    definition: IntegrationKnowledgeSourceDefinition
