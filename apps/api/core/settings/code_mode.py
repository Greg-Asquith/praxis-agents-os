"""Sandboxed code-mode execution settings."""

from pydantic import Field, model_validator


class CodeModeSettingsMixin:
    AGENT_CODE_MODE_POOL_SIZE: int = Field(
        default=2,
        ge=1,
        description="Monty subprocesses maintained by each code-mode runtime process.",
    )
    AGENT_CODE_MODE_TIMEOUT_SECONDS: float = Field(
        default=60.0,
        gt=0,
        description="Cumulative wall-clock and interpreter duration limit for one script.",
    )
    AGENT_CODE_MODE_CHECKOUT_TIMEOUT_SECONDS: float = Field(
        default=5.0,
        gt=0,
        description="Maximum wait for an available Monty subprocess.",
    )
    AGENT_CODE_MODE_REQUEST_TIMEOUT_SECONDS: float = Field(
        default=65.0,
        gt=0,
        description="Monty worker-request backstop that replaces an unresponsive subprocess.",
    )
    AGENT_CODE_MODE_MAX_NESTED_CALLS: int = Field(
        default=25,
        ge=1,
        description="Maximum serial nested tool calls in one script execution.",
    )
    AGENT_CODE_MODE_OUTPUT_MAX_CHARS: int = Field(
        default=8_000,
        ge=1,
        description="Maximum captured print-output characters per script.",
    )
    AGENT_CODE_MODE_VALUE_MAX_BYTES: int = Field(
        default=262_144,
        ge=1,
        description="Maximum serialized bytes for each value crossing the Monty boundary.",
    )
    AGENT_CODE_MODE_MEMORY_MAX_BYTES: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        description="Monty interpreter memory limit for one script checkout.",
    )
    AGENT_CODE_MODE_MAX_RECURSION_DEPTH: int = Field(
        default=100,
        ge=1,
        description="Monty interpreter recursion-depth limit for one script checkout.",
    )
    AGENT_CODE_MODE_GC_INTERVAL: int = Field(
        default=1_000,
        ge=1,
        description="Monty interpreter allocation interval between garbage collections.",
    )

    @model_validator(mode="after")
    def validate_code_mode_timeouts(self):
        """Keep the worker-kill backstop behind normal script cancellation."""
        if self.AGENT_CODE_MODE_REQUEST_TIMEOUT_SECONDS <= self.AGENT_CODE_MODE_TIMEOUT_SECONDS:
            raise ValueError(
                "AGENT_CODE_MODE_REQUEST_TIMEOUT_SECONDS must exceed "
                "AGENT_CODE_MODE_TIMEOUT_SECONDS"
            )
        return self
