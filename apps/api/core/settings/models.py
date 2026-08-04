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
        default="gpt-5.4-nano",
        description="Model used to generate conversation titles.",
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
        default="global", description="Vertex AI location, e.g. 'global' or 'us-central1'."
    )

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
        missing: list[str] = []
        for provider in active_providers:
            if provider == "google" and self.GOOGLE_VERTEX_AI:
                # Vertex authenticates via ADC; it needs a project, not an API key.
                if not (self.GOOGLE_VERTEX_PROJECT or getattr(self, "GCP_PROJECT_ID", None)):
                    missing.append("GOOGLE_VERTEX_PROJECT")
                continue
            attr = _PROVIDER_KEY_ATTR.get(provider)
            if attr is None:
                raise ValueError(f"Unknown LLM provider configured: '{provider}'")
            if getattr(self, attr) is None:
                missing.append(attr)

        if (
            self.DEFAULT_MODEL_PROVIDER == "azure"
            and not (self.AZURE_OPENAI_ENDPOINT or "").strip()
        ):
            missing.append("AZURE_OPENAI_ENDPOINT")

        if missing:
            raise ValueError(
                "Missing LLM provider credentials in production: " + ", ".join(sorted(set(missing)))
            )
        return self
