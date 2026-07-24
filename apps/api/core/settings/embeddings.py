# apps/api/core/settings/embeddings.py

"""Embedding provider, vector-shape, and usage-budget settings."""

from typing import Literal

from pydantic import Field, model_validator


class EmbeddingsSettingsMixin:
    EMBEDDINGS_PROVIDER: Literal["openai", "google", "ollama"] = Field(
        default="openai",
        description="Embedding provider for knowledge-base and memory vectors.",
    )
    EMBEDDINGS_MODEL: str = Field(
        default="text-embedding-3-small",
        description="Embedding model id from the embedding registry.",
    )
    EMBEDDINGS_DIMENSIONS: int = Field(
        default=1024,
        ge=512,
        le=1024,
        description=(
            "Vector dimensions; Matryoshka-truncated where supported and recorded per collection."
        ),
    )
    EMBEDDINGS_MAX_BATCH_TEXTS: int = Field(
        default=64,
        gt=0,
        description="Maximum texts per provider embedding request.",
    )
    EMBEDDINGS_MAX_TEXT_CHARS: int = Field(
        default=32_000,
        gt=0,
        description="Per-text character cap; callers must chunk longer inputs.",
    )
    EMBEDDINGS_OLLAMA_BASE_URL: str | None = Field(
        default=None,
        description="Explicit Ollama base URL, required when the Ollama provider is selected.",
    )
    EMBEDDINGS_MONTHLY_TOKEN_BUDGET: int = Field(
        default=2_000_000,
        gt=0,
        description="Observed, soft monthly embedding-token budget per workspace.",
    )

    @model_validator(mode="after")
    def validate_embedding_provider_config(self):
        """Require explicit connectivity for the selected embedding provider."""
        if (
            self.EMBEDDINGS_PROVIDER == "ollama"
            and not (self.EMBEDDINGS_OLLAMA_BASE_URL or "").strip()
        ):
            raise ValueError("EMBEDDINGS_PROVIDER=ollama requires EMBEDDINGS_OLLAMA_BASE_URL")

        credential_setting = {
            "google": "GOOGLE_API_KEY",
            "openai": "OPENAI_API_KEY",
        }.get(self.EMBEDDINGS_PROVIDER)
        if getattr(self, "ENVIRONMENT", None) == "production" and credential_setting:
            secret = getattr(self, credential_setting, None)
            if secret is None or not secret.get_secret_value().strip():
                raise ValueError(
                    f"EMBEDDINGS_PROVIDER={self.EMBEDDINGS_PROVIDER} requires "
                    f"{credential_setting} in production"
                )
        return self
