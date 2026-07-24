# apps/api/core/settings/kb.py

"""Knowledge-base ingestion and retention settings."""

from pydantic import Field, model_validator


class KBSettingsMixin:
    KB_CHUNK_TARGET_TOKENS: int = Field(
        default=600,
        gt=0,
        le=10_000,
        description="Greedy markdown chunk target using the character heuristic.",
    )
    KB_CHUNK_MAX_TOKENS: int = Field(
        default=800,
        gt=0,
        le=10_000,
        description="Hard token-estimate ceiling for one knowledge-base chunk.",
    )
    KB_CHUNK_OVERLAP_TOKENS: int = Field(
        default=80,
        ge=0,
        le=5_000,
        description="Trailing context carried into the next markdown chunk.",
    )
    KB_MAX_DOCUMENT_BYTES: int = Field(
        default=2_000_000,
        gt=0,
        le=20_000_000,
        description="Maximum UTF-8 bytes retained as canonical document markdown.",
    )
    KB_URL_FETCH_TIMEOUT_SECONDS: float = Field(
        default=30.0,
        gt=0,
        le=120,
        description="Total timeout for one knowledge-base URL fetch hop.",
    )
    KB_URL_MAX_BYTES: int = Field(
        default=5_000_000,
        gt=0,
        le=20_000_000,
        description="Maximum response bytes accepted from a knowledge-base URL.",
    )
    KB_URL_MAX_REDIRECTS: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum validated redirects followed during URL ingestion.",
    )
    KB_ANNOTATION_PROVIDER: str = Field(
        default="openai",
        min_length=1,
        max_length=32,
        description="Utility-model provider used for contextual chunk annotation.",
    )
    KB_ANNOTATION_MODEL: str = Field(
        default="gpt-5.6-luna",
        min_length=1,
        max_length=128,
        description="Utility model used for contextual chunk annotation.",
    )
    KB_ANNOTATION_MAX_CHUNKS: int = Field(
        default=200,
        gt=0,
        le=2_000,
        description="Maximum chunks annotated for one document ingestion.",
    )
    KB_ANNOTATION_CONTEXT_MAX_CHARS: int = Field(
        default=500,
        gt=0,
        le=2_000,
        description="Hard character cap for a generated chunk context line.",
    )
    KB_SWEEP_INTERVAL_SECONDS: int = Field(
        default=3_600,
        gt=0,
        le=86_400,
        description="Delay between knowledge-base retention sweeps.",
    )
    KB_DELETED_RETENTION_DAYS: int = Field(
        default=30,
        ge=1,
        le=3_650,
        description="Days to retain soft-deleted knowledge-base documents.",
    )

    @model_validator(mode="after")
    def validate_kb_chunk_settings(self):
        """Keep target and overlap values inside the hard chunk ceiling."""
        if self.KB_CHUNK_TARGET_TOKENS > self.KB_CHUNK_MAX_TOKENS:
            raise ValueError("KB_CHUNK_TARGET_TOKENS must not exceed KB_CHUNK_MAX_TOKENS")
        if self.KB_CHUNK_OVERLAP_TOKENS >= self.KB_CHUNK_TARGET_TOKENS:
            raise ValueError("KB_CHUNK_OVERLAP_TOKENS must be less than KB_CHUNK_TARGET_TOKENS")
        return self
