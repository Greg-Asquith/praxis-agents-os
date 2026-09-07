# apps/api/services/agents/models/validate_partner_configuration.py

"""Validate partner catalog routing before any provider request."""

from core.settings import settings
from services.agents.models.domain import (
    VERTEX_PARTNER_PROVIDERS,
    ModelConfigurationError,
)
from services.agents.models.registry import find_model, list_models
from services.agents.models.utils import partner_location


def validate_partner_configuration() -> None:
    """Reject unknown overrides and incomplete active partner routing metadata."""
    for alias in settings.VERTEX_PARTNER_MODEL_LOCATIONS:
        provider, _, model = alias.partition(":")
        info = find_model(provider, model)
        if info is None or info.deprecated or provider not in VERTEX_PARTNER_PROVIDERS:
            raise ModelConfigurationError(
                f"VERTEX_PARTNER_MODEL_LOCATIONS contains unknown partner model '{alias}'.",
                details={"setting": "VERTEX_PARTNER_MODEL_LOCATIONS", "model": alias},
            )
        partner_location(info)
    if settings.VERTEX_PARTNER_MODELS_ENABLED:
        for info in list_models():
            if info.provider in VERTEX_PARTNER_PROVIDERS:
                partner_location(info)
