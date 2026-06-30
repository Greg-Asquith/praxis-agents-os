# apps/api/services/agents/models/__init__.py

"""Model registry, resolution, and factory for the agent runtime."""

from services.agents.models.factory import build_model
from services.agents.models.registry import (
    find_model,
    get_model,
    is_known,
    list_models,
    qualified_id,
)
from services.agents.models.resolution import resolve_agent_model, resolve_naming_model
from services.agents.models.utils import provider_api_key

__all__ = [
    "build_model",
    "find_model",
    "get_model",
    "is_known",
    "list_models",
    "provider_api_key",
    "qualified_id",
    "resolve_agent_model",
    "resolve_naming_model",
]
