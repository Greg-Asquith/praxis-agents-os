# apps/api/services/agents/models/validate_vertex_configuration.py

"""Validate Vertex model lists and partner routing before any provider request."""

from core.settings import settings
from services.agents.models.domain import (
    PROVIDER_ANTHROPIC,
    VERTEX_PARTNER_PROVIDERS,
    ModelConfigurationError,
    has_vertex_model_id,
)
from services.agents.models.registry import find_model
from services.agents.models.utils import partner_location


def validate_vertex_configuration() -> None:
    """Reject unknown Vertex model entries and incomplete partner routing metadata."""
    for model in settings.ANTHROPIC_VERTEX_MODELS:
        info = find_model(PROVIDER_ANTHROPIC, model)
        if info is None or info.deprecated or not has_vertex_model_id(info.vertex_model):
            raise ModelConfigurationError(
                f"ANTHROPIC_VERTEX_MODELS contains unknown Vertex model '{model}'.",
                details={"setting": "ANTHROPIC_VERTEX_MODELS", "model": model},
            )
    for setting_name in ("VERTEX_PARTNER_MODELS", "VERTEX_PARTNER_MODEL_LOCATIONS"):
        for alias in getattr(settings, setting_name):
            provider, _, model = alias.partition(":")
            info = find_model(provider, model)
            if info is None or info.deprecated or provider not in VERTEX_PARTNER_PROVIDERS:
                raise ModelConfigurationError(
                    f"{setting_name} contains unknown partner model '{alias}'.",
                    details={"setting": setting_name, "model": alias},
                )
            partner_location(info)
