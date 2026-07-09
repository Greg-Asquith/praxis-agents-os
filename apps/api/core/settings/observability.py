# apps/api/core/settings/observability.py

"""Agent runtime observability settings."""

from pydantic import Field, model_validator


class ObservabilitySettingsMixin:
    METRICS_ENABLED: bool = Field(default=False, description="Expose /api/metrics.")
    METRICS_TOKEN: str | None = Field(
        default=None,
        description="Bearer token required by /api/metrics.",
    )

    AGENT_TRACING_ENABLED: bool = Field(
        default=False,
        description="Emit OpenTelemetry spans for agent runs, model requests, and tool calls.",
    )
    AGENT_TRACING_INCLUDE_CONTENT: bool = Field(
        default=False,
        description=(
            "Include prompts, completions, and tool arguments in agent spans. "
            "Keep disabled outside local debugging."
        ),
    )
    AGENT_TRACING_ALLOW_CONTENT_IN_PRODUCTION: bool = Field(
        default=False,
        description="Allow content-capturing agent spans when ENVIRONMENT=production.",
    )

    @model_validator(mode="after")
    def reject_agent_trace_content_in_production(self):
        """Content-bearing traces can contain workspace data; require explicit prod opt-in."""
        if (
            getattr(self, "ENVIRONMENT", None) == "production"
            and self.AGENT_TRACING_INCLUDE_CONTENT
            and not self.AGENT_TRACING_ALLOW_CONTENT_IN_PRODUCTION
        ):
            raise ValueError(
                "AGENT_TRACING_INCLUDE_CONTENT requires "
                "AGENT_TRACING_ALLOW_CONTENT_IN_PRODUCTION when ENVIRONMENT=production"
            )
        return self
