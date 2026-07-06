# apps/api/core/settings/agents.py

"""Agent runtime durability settings."""

from pydantic import Field


class AgentRunSettingsMixin:
    AGENT_SCHEDULE_WORKER_POLL_SECONDS: float = Field(
        default=5.0,
        gt=0,
        description="Seconds between scheduled agent runner polling passes.",
    )
    AGENT_SCHEDULE_WORKER_BATCH_SIZE: int = Field(
        default=25,
        gt=0,
        description="Maximum schedule fire times claimed by one worker polling pass.",
    )
    AGENT_SCHEDULE_RUN_CLAIM_TTL_SECONDS: int = Field(
        default=300,
        gt=0,
        description="Seconds before a claimed schedule run can be reclaimed.",
    )
    AGENT_SCHEDULE_RUN_MAX_ATTEMPTS: int = Field(
        default=3,
        gt=0,
        description="Maximum claim/setup attempts before disabling a schedule.",
    )
    AGENT_SCHEDULE_WORKER_SHUTDOWN_SECONDS: float = Field(
        default=30.0,
        gt=0,
        description="Seconds to wait for scheduled worker shutdown.",
    )
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
    AGENT_RUN_TOTAL_TOKENS_LIMIT: int | None = Field(
        default=None,
        gt=0,
        description="Maximum total (input+output) tokens per agent run; None disables the cap.",
    )
    AGENT_HISTORY_MAX_TURNS: int | None = Field(
        default=40,
        gt=0,
        description="Prior-user-turn count that triggers a history trim; None sends full history.",
    )
    AGENT_HISTORY_KEEP_TURNS: int = Field(
        default=20,
        gt=0,
        description="Prior user turns retained after a trim; must be below AGENT_HISTORY_MAX_TURNS.",
    )
    AGENT_PROMPT_CACHE_ENABLED: bool = Field(
        default=True,
        description="Enable provider-native prompt caching where the provider needs explicit opt-in.",
    )
