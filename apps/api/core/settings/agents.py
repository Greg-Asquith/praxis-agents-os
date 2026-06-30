# apps/api/core/settings/agents.py

"""Agent runtime durability settings."""

from pydantic import Field


class AgentRunSettingsMixin:
    AGENT_RUN_LEASE_TTL_SECONDS: int = Field(
        default=90,
        gt=0,
        description="Seconds before an unrenewed interactive agent run lease is stale.",
    )
    AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS: int = Field(
        default=30,
        gt=0,
        description="Seconds between lease renewals for interactive agent turns.",
    )
    AGENT_RUN_MAX_DURATION_SECONDS: int = Field(
        default=1200,
        gt=0,
        description="Hard maximum runtime before an observed agent run can be reaped.",
    )
    AGENT_RUN_REAPER_INTERVAL_SECONDS: int = Field(
        default=30,
        gt=0,
        description="Default interval for future periodic abandoned-run sweeps.",
    )
    AGENT_RUN_SHUTDOWN_DRAIN_SECONDS: float = Field(
        default=120.0,
        gt=0,
        description="Seconds to wait for detached agent turns during API shutdown.",
    )
    AGENT_RUN_STREAM_KEEPALIVE_SECONDS: float = Field(
        default=15.0,
        gt=0,
        description="Seconds of SSE idleness before emitting a keepalive comment frame.",
    )
    AGENT_RUN_PENDING_GRACE_SECONDS: int = Field(
        default=60,
        gt=0,
        description="Grace period before an unleased pending run is considered abandoned.",
    )
