# apps/api/core/settings/scratch.py

"""Agent scratch-space settings."""

from pydantic import Field


class ScratchSettingsMixin:
    SCRATCH_TTL_DAYS: int = Field(
        default=30,
        gt=0,
        description="Rolling retention window, in days, for agent scratch entries.",
    )
    SCRATCH_MAX_ENTRY_BYTES: int = Field(
        default=262144,
        gt=0,
        description="Maximum UTF-8 byte size for one agent scratch entry.",
    )
    SCRATCH_MAX_ENTRIES_PER_SCOPE: int = Field(
        default=20,
        gt=0,
        description="Maximum scratch entries per conversation or run scope.",
    )
    SCRATCH_SWEEP_INTERVAL_SECONDS: int = Field(
        default=3600,
        gt=0,
        description="Seconds between expired scratch retention sweeps.",
    )
    READ_FILE_MAX_CONTENT_BYTES: int = Field(
        default=49152,
        gt=0,
        description="Default maximum UTF-8 byte slice returned by read_file content mode.",
    )
    AVAILABLE_FILES_PROMPT_BUDGET: int = Field(
        default=4000,
        gt=0,
        description="Soft character budget for the available-files runtime prompt block.",
    )
    AVAILABLE_FILES_MAX_LISTED: int = Field(
        default=50,
        gt=0,
        description="Maximum conversation-attached files listed in the runtime prompt block.",
    )
