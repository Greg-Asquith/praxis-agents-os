# apps/api/services/agents/models/domain.py

"""Model-runtime value types: provider constants, catalog/spec records, errors.

The catalog is Python-owned (registry.py). These types describe a single known
model and a fully-resolved model spec ready for the factory to instantiate.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from core.exceptions.general import ProblemDetailsError

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDER_GOOGLE = "google"
PROVIDER_AZURE = "azure"

ALL_PROVIDERS = frozenset(
    {PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_GOOGLE, PROVIDER_AZURE}
)

# Fallback step ceiling when an agent does not pin max_steps.
DEFAULT_MAX_STEPS = 20


class ModelConfigurationError(ProblemDetailsError):
    """Raised when a model cannot be resolved or constructed.

    Covers unknown/deprecated catalog entries, unsupported providers, and missing
    provider credentials. Treated as a server-side configuration fault (500).
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(
            message,
            status_code=500,
            title="Model Configuration Error",
            details=details,
        )


@dataclass(frozen=True)
class ModelInfo:
    """One known model in the Python-owned catalog."""

    provider: str
    model: str
    display_name: str
    context_window: int
    supports_tools: bool = True
    supports_thinking: bool = False
    supports_vision: bool = False
    supports_structured_output: bool = True
    default_settings: Mapping[str, Any] = field(default_factory=dict)
    deprecated: bool = False

    @property
    def qualified_id(self) -> str:
        """Provider-qualified id consumed by Pydantic AI, e.g. 'openai:gpt-5.4-mini'."""
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class ResolvedModel:
    """A fully-resolved model spec: which model, merged settings, step ceiling."""

    provider: str
    model: str
    settings: Mapping[str, Any]
    max_steps: int
    azure_deployment: str | None = None

    @property
    def qualified_id(self) -> str:
        return f"{self.provider}:{self.model}"
