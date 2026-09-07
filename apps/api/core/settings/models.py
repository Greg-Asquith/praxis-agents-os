# apps/api/core/settings/models.py

"""LLM model selection and provider credential settings.

Separate from infrastructure provider selection in providers.py: this concerns
which LLM models the agent runtime uses and the API keys needed to reach them.
The model catalog itself is Python-owned in services/agents/models/registry.py;
these settings only pick defaults and hold credentials.
"""

import re

from pydantic import Field, SecretStr, field_validator, model_validator

_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)

# Provider -> API key setting name. Kept in sync with the runtime credential
# seam in services/agents/models/utils.py (settings cannot import services).
_PROVIDER_KEY_ATTR = {
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
}


class LLMSettingsMixin:
    # Default provider/model for agents that do not pin their own.
    DEFAULT_MODEL_PROVIDER: str = Field(
        default="openai",
        description="Provider used when an agent does not specify model_provider.",
    )
    DEFAULT_MODEL: str = Field(
        default="gpt-5.6-luna",
        description="Model used when an agent does not specify model.",
    )

    # Hard-coded utility use case: naming conversations.
    CONVERSATION_NAMING_PROVIDER: str = Field(
        default="openai",
        description="Provider for the conversation-naming utility model.",
    )
    CONVERSATION_NAMING_MODEL: str = Field(
        default="gpt-5.6-luna",
        description="Model used to generate conversation titles.",
    )
    NATIVE_CLASSIFIER_PROVIDER: str = Field(
        default="openai",
        description="Default provider for native classifier helper calls.",
    )
    NATIVE_CLASSIFIER_MODEL: str = Field(
        default="gpt-5.6-luna",
        description="Default model for native classifier helper calls.",
    )
    NATIVE_CLASSIFIER_MAX_ITEMS: int = Field(
        default=500,
        ge=1,
        le=500,
        description="Maximum items accepted by one native classifier call.",
    )
    NATIVE_CLASSIFIER_MAX_ITEM_CHARS: int = Field(
        default=4_000,
        ge=1,
        description="Maximum characters accepted in one native classifier item.",
    )
    NATIVE_CLASSIFIER_MAX_LABELS: int = Field(
        default=50,
        ge=2,
        description="Maximum labels accepted by one native classifier call.",
    )
    NATIVE_CLASSIFIER_MAX_STEPS: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Maximum model requests for one native classifier helper run.",
    )
    NATIVE_WEB_SEARCH_MAX_STEPS: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum model requests for one native web-search helper run.",
    )
    NATIVE_WEB_FETCH_MAX_STEPS: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum model requests for one native web-fetch helper run.",
    )
    NATIVE_WEB_FETCH_MAX_CONTENT_TOKENS: int = Field(
        default=20_000,
        ge=1_000,
        le=100_000,
        description="Provider-side content-token cap for one native web fetch.",
    )
    NATIVE_WEB_FETCH_BLOCKED_DOMAINS: str = Field(
        default="",
        description=(
            "Comma-separated domains that native web fetch must refuse. Configuring this "
            "policy limits native web fetch to providers that enforce domain filtering."
        ),
    )

    @field_validator("NATIVE_WEB_FETCH_BLOCKED_DOMAINS")
    @classmethod
    def validate_native_web_fetch_blocked_domains(cls, value: str) -> str:
        domains = tuple(
            dict.fromkeys(domain.strip().lower().rstrip(".") for domain in value.split(","))
        )
        invalid = [domain for domain in domains if domain and not _DOMAIN_PATTERN.fullmatch(domain)]
        if invalid:
            raise ValueError(
                "NATIVE_WEB_FETCH_BLOCKED_DOMAINS entries must be bare domain names: "
                + ", ".join(invalid)
            )
        return ",".join(domain for domain in domains if domain)

    # Provider HTTP retry policy. Max attempts of 1 means one try and no retry.
    LLM_HTTP_RETRY_MAX_ATTEMPTS: int = Field(
        default=4,
        gt=0,
        description="Maximum provider HTTP attempts; set to 1 to disable retries.",
    )
    LLM_HTTP_RETRY_MAX_WAIT_SECONDS: float = Field(
        default=60.0,
        gt=0,
        description="Maximum exponential-backoff wait in seconds between provider HTTP retries.",
    )
    LLM_HTTP_RETRY_TOTAL_WAIT_CAP_SECONDS: float = Field(
        default=120.0,
        gt=0,
        description="Maximum wait honored from provider Retry-After headers, in seconds.",
    )

    # Provider credentials. Nullable so local/dev can run without every key;
    # required in production for the active providers (validated below).
    ANTHROPIC_API_KEY: SecretStr | None = Field(default=None, description="Anthropic API key.")
    OPENAI_API_KEY: SecretStr | None = Field(default=None, description="OpenAI API key.")
    # Passed explicitly to every OpenAI client so an ambient OPENAI_BASE_URL
    # env var can never silently redirect or break provider requests.
    OPENAI_BASE_URL: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI API base URL; blank values fall back to the official endpoint.",
    )
    GOOGLE_API_KEY: SecretStr | None = Field(
        default=None,
        description="Google AI (Gemini Developer API) key. Unused when GOOGLE_VERTEX_AI.",
    )

    # Google Cloud / Vertex AI. When enabled, Google models route through Vertex
    # using Application Default Credentials (no API key); project falls back to
    # the infra GCP_PROJECT_ID when GOOGLE_VERTEX_PROJECT is unset.
    GOOGLE_VERTEX_AI: bool = Field(
        default=False,
        description="Route Google models through Vertex AI instead of the Gemini API.",
    )
    GOOGLE_VERTEX_PROJECT: str | None = Field(
        default=None, description="GCP project for Vertex AI. Falls back to GCP_PROJECT_ID."
    )
    GOOGLE_VERTEX_LOCATION: str = Field(
        default="auto",
        description=(
            "Vertex AI location. Auto uses catalog defaults for Gemini and global for "
            "embeddings. Explicit locations must be supported by the selected model."
        ),
    )
    ANTHROPIC_VERTEX_AI: bool = Field(
        default=False,
        description=(
            "Route Anthropic models through Vertex AI with Application Default Credentials. "
            "The project uses GOOGLE_VERTEX_PROJECT, then GCP_PROJECT_ID."
        ),
    )
    ANTHROPIC_VERTEX_LOCATION: str = Field(
        default="global",
        description=(
            "Vertex AI location for Anthropic models using Application Default Credentials. "
            "The project uses GOOGLE_VERTEX_PROJECT, then GCP_PROJECT_ID."
        ),
    )
    VERTEX_PARTNER_MODELS_ENABLED: bool = Field(
        default=False,
        description=(
            "Expose Vertex AI partner models through Application Default Credentials. "
            "The project uses GOOGLE_VERTEX_PROJECT, then GCP_PROJECT_ID."
        ),
    )
    VERTEX_PARTNER_MODEL_LOCATIONS: dict[str, str] = Field(
        default_factory=dict,
        description="Vertex partner location overrides keyed by provider-qualified catalog alias.",
    )
    VERTEX_PARTNER_LOCATION: str | None = Field(default=None, exclude=True, repr=False)

    @field_validator("VERTEX_PARTNER_LOCATION", mode="before")
    @classmethod
    def reject_legacy_partner_location(cls, value):
        if value is not None:
            raise ValueError(
                "VERTEX_PARTNER_LOCATION was removed. Remove it to use model defaults, "
                "or migrate to VERTEX_PARTNER_MODEL_LOCATIONS JSON keyed by catalog alias."
            )
        return value

    @field_validator("VERTEX_PARTNER_MODEL_LOCATIONS", mode="before")
    @classmethod
    def validate_partner_location_shape(cls, value):
        if not isinstance(value, dict) or any(
            not isinstance(key, str)
            or not isinstance(location, str)
            or not key.strip()
            or not location.strip()
            for key, location in value.items()
        ):
            raise ValueError("VERTEX_PARTNER_MODEL_LOCATIONS must be a JSON object of strings.")
        return value

    # Azure OpenAI (deployment-based; uses the agent's azure_deployment at resolution).
    AZURE_OPENAI_API_KEY: SecretStr | None = Field(
        default=None, description="Azure OpenAI API key."
    )
    AZURE_OPENAI_ENDPOINT: str | None = Field(
        default=None, description="Azure OpenAI endpoint, e.g. https://<resource>.openai.azure.com."
    )
    AZURE_OPENAI_API_VERSION: str = Field(
        default="2024-10-21", description="Azure OpenAI API version."
    )
    AZURE_OPENAI_CONTEXT_WINDOW: int = Field(
        default=128_000,
        gt=0,
        description=(
            "Context window for Azure OpenAI deployments; override to match the deployed model."
        ),
    )
    AZURE_OPENAI_CHARS_PER_TOKEN: float = Field(
        default=4.0,
        gt=0,
        description="Calibrated character-to-token estimate for Azure OpenAI deployments.",
    )

    @field_validator("OPENAI_BASE_URL", mode="before")
    @classmethod
    def coerce_blank_openai_base_url(cls, value):
        """Treat blank env values as unset instead of producing schemeless URLs."""
        if value is None or not str(value).strip():
            return "https://api.openai.com/v1"
        return str(value).strip()

    @model_validator(mode="after")
    def validate_llm_provider_credentials(self):
        """Require credentials for the active providers in production.

        Active providers back the default agent, conversation naming, or history
        summarization. Local/development may run without keys; tests construct
        settings without them. Registry membership is validated at resolution
        time, not here, to keep settings free of service imports.
        """
        environment = getattr(self, "ENVIRONMENT", None)
        if environment != "production":
            return self

        active_providers = {
            self.DEFAULT_MODEL_PROVIDER,
            self.CONVERSATION_NAMING_PROVIDER,
            self.AGENT_HISTORY_SUMMARY_MODEL_PROVIDER,
        }
        missing = [
            requirement
            for provider in active_providers
            if (requirement := self._missing_provider_requirement(provider)) is not None
        ]
        if requirement := self._missing_azure_endpoint_requirement():
            missing.append(requirement)

        if missing:
            raise ValueError(
                "Missing LLM provider credentials in production: " + ", ".join(sorted(set(missing)))
            )
        return self

    def _missing_provider_requirement(self, provider: str) -> str | None:
        if provider == "anthropic" and self.ANTHROPIC_VERTEX_AI:
            return self._missing_vertex_project_requirement()
        if provider == "google" and self.GOOGLE_VERTEX_AI:
            return self._missing_vertex_project_requirement()
        if provider in {"meta", "mistral", "xai"}:
            if not self.VERTEX_PARTNER_MODELS_ENABLED:
                raise ValueError(
                    f"LLM provider '{provider}' requires VERTEX_PARTNER_MODELS_ENABLED=true"
                )
            return self._missing_vertex_project_requirement()

        attr = _PROVIDER_KEY_ATTR.get(provider)
        if attr is None:
            raise ValueError(f"Unknown LLM provider configured: '{provider}'")
        credential = getattr(self, attr)
        return attr if credential is None or not credential.get_secret_value().strip() else None

    def _missing_vertex_project_requirement(self) -> str | None:
        return None if self._vertex_project() else "GOOGLE_VERTEX_PROJECT or GCP_PROJECT_ID"

    def _missing_azure_endpoint_requirement(self) -> str | None:
        if (
            self.DEFAULT_MODEL_PROVIDER == "azure"
            and not (self.AZURE_OPENAI_ENDPOINT or "").strip()
        ):
            return "AZURE_OPENAI_ENDPOINT"
        return None

    def _vertex_project(self) -> str | None:
        for project in (self.GOOGLE_VERTEX_PROJECT, getattr(self, "GCP_PROJECT_ID", None)):
            normalized = (project or "").strip()
            if normalized:
                return normalized
        return None
