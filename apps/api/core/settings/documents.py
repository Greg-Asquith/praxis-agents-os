# apps/api/core/settings/documents.py

"""Office document worker bounds."""

from pydantic import Field, model_validator

_MIB = 1024 * 1024


class DocumentToolsSettingsMixin:
    DOCUMENT_TOOLS_MAX_SOURCE_BYTES: int = Field(
        default=50 * _MIB,
        ge=1,
        description="Largest Office file sent to the document worker.",
    )
    DOCUMENT_TOOLS_MAX_UNCOMPRESSED_BYTES: int = Field(
        default=200 * _MIB,
        ge=1,
        description="Largest declared uncompressed size across all parts of one Office file.",
    )
    DOCUMENT_TOOLS_MAX_ZIP_ENTRIES: int = Field(
        default=5_000,
        ge=1,
        description="Most parts allowed in one Office file.",
    )
    DOCUMENT_TOOLS_MAX_COMPRESSION_RATIO: int = Field(
        default=100,
        ge=1,
        description="Highest uncompressed-to-compressed ratio allowed for one large part.",
    )
    DOCUMENT_TOOLS_MAX_OPERATIONS: int = Field(
        default=500,
        ge=1,
        description="Most edit operations accepted in one document tool call.",
    )
    DOCUMENT_TOOLS_READ_MAX_CHARS: int = Field(
        default=60_000,
        ge=1,
        description="Largest page of text returned by one document read.",
    )
    DOCUMENT_TOOLS_TIMEOUT_SECONDS: float = Field(
        default=60.0,
        gt=0,
        description="Wall-clock limit for one document worker call; the worker is killed after it.",
    )
    DOCUMENT_TOOLS_WORKER_MEMORY_BYTES: int = Field(
        default=1024 * _MIB,
        ge=256 * _MIB,
        description="Address-space limit for each document worker process.",
    )
    DOCUMENT_TOOLS_WORKERS: int = Field(
        default=2,
        ge=1,
        description="Document worker processes kept by each API or worker process.",
    )

    @model_validator(mode="after")
    def validate_document_tool_bounds(self):
        """Keep the source bound inside the uncompressed bound the worker enforces."""
        if self.DOCUMENT_TOOLS_MAX_SOURCE_BYTES > self.DOCUMENT_TOOLS_MAX_UNCOMPRESSED_BYTES:
            raise ValueError(
                "DOCUMENT_TOOLS_MAX_SOURCE_BYTES cannot exceed DOCUMENT_TOOLS_MAX_UNCOMPRESSED_BYTES"
            )
        return self
