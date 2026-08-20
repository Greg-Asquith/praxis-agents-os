# apps/api/services/agents/runtime/tools/native/classifier_contract.py

"""Shared configuration contract for native and workspace classifiers."""

from typing import Literal

from services.agents.models.domain import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
)

ClassifierProvider = Literal["openai", "anthropic", "google"]

SUPPORTED_CLASSIFIER_PROVIDERS = (
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
)
CLASSIFIER_MAX_INSTRUCTIONS_CHARS = 4_000
