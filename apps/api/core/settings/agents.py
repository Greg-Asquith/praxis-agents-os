# apps/api/core/settings/agents.py

"""Agent runtime durability settings."""

from typing import Literal

from pydantic import Field


class AgentRunSettingsMixin:
    WORKER_MODE: Literal["forever", "drain"] = Field(
        default="forever",
        description="Worker process lifecycle: poll forever or drain available work and exit.",
    )
    WORKER_DRAIN_MAX_SECONDS: float = Field(
        default=300.0,
        gt=0,
        description="Maximum wall-clock seconds for one worker drain execution.",
    )
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
    AGENT_RUN_APPROVAL_EXPIRY_DAYS: int = Field(
        default=7,
        ge=0,
        description="Days before a parked approval expires; 0 disables expiry.",
    )
    AGENT_RUN_TOTAL_TOKENS_LIMIT: int | None = Field(
        default=1_000_000,
        gt=0,
        description=(
            "Maximum total (input+output) tokens per agent run; None disables the runaway-loop "
            "backstop."
        ),
    )
    AGENT_TOOL_RESULT_MAX_CHARS: int | None = Field(
        default=16_000,
        gt=0,
        description="Maximum free-text tool-result characters; None disables the bound.",
    )
    NATIVE_IMAGE_GENERATION_MAX_STEPS: int = Field(
        default=3,
        gt=0,
        description="Maximum helper-model requests for one native image generation call.",
    )
    NATIVE_IMAGE_EDITING_MAX_INPUT_BYTES: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        le=64 * 1024 * 1024,
        description="Maximum combined raw workspace image bytes for one image-editing call.",
    )
    NATIVE_VIDEO_TO_IMAGE_MAX_INPUT_BYTES: int = Field(
        default=18 * 1024 * 1024,
        ge=1,
        le=20 * 1024 * 1024,
        description="Maximum inline workspace video bytes for one video-to-image helper call.",
    )
    AGENT_SCHEDULED_SIDE_EFFECT_POLICY: Literal["allow", "require_approval", "deny"] = Field(
        default="require_approval",
        description="Side-effect policy minted for scheduled agent runs.",
    )
    AGENT_MAX_DELEGATION_DEPTH: int = Field(
        default=1,
        ge=0,
        description="Maximum nested delegated-agent depth allowed for one run.",
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
    AGENT_HISTORY_DB_MAX_MESSAGES: int = Field(
        default=500,
        ge=50,
        le=5000,
        description="Max persisted messages loaded per turn before trimming.",
    )
    AGENT_HISTORY_CONTEXT_FRACTION: float = Field(
        default=0.6,
        gt=0,
        le=1,
        description="Fraction of the model context window available before history tightens.",
    )
    AGENT_HISTORY_SUMMARY_MAX_CHARS: int = Field(
        default=2000,
        gt=0,
        description="Maximum stored characters in one automatic conversation summary.",
    )
    AGENT_HISTORY_SUMMARY_MODEL_PROVIDER: str = Field(
        default="openai",
        description="Provider for the out-of-band conversation history summarizer.",
    )
    AGENT_HISTORY_SUMMARY_MODEL: str = Field(
        default="gpt-5.6-luna",
        description="Model for the out-of-band conversation history summarizer.",
    )
    AGENT_PROMPT_IDENTITY_BUDGET: int = Field(
        default=12_000,
        gt=0,
        description="Soft character budget for agent identity instructions.",
    )
    AGENT_PROMPT_ACTIVE_CONTEXT_BUDGET: int = Field(
        default=2000,
        gt=0,
        description="Soft character budget for active integration context.",
    )
    AGENT_PROMPT_PLANNING_BUDGET: int = Field(
        default=2000,
        gt=0,
        description="Soft character budget for planning instructions.",
    )
    AGENT_PROMPT_DELEGATION_BUDGET: int = Field(
        default=2400,
        gt=0,
        description="Soft character budget for delegation instructions.",
    )
    AGENT_PROMPT_KNOWLEDGE_BUDGET: int = Field(
        default=1200,
        gt=0,
        description="Soft character budget for knowledge instructions.",
    )
    AGENT_PROMPT_UNTRUSTED_POLICY_BUDGET: int = Field(
        default=1200,
        gt=0,
        description="Soft character budget for the untrusted-content policy.",
    )
    AGENT_PROMPT_CACHE_ENABLED: bool = Field(
        default=True,
        description="Enable provider-native prompt caching where the provider needs explicit opt-in.",
    )
