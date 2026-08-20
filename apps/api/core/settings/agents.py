# apps/api/core/settings/agents.py

"""Agent runtime durability settings."""

import logging
from typing import Literal

from pydantic import Field, model_validator

logger = logging.getLogger(__name__)


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
    WORKER_MAX_CONCURRENT_RUNS: int = Field(
        default=4,
        ge=1,
        description=(
            "Maximum scheduled runs and generic jobs active per worker process; "
            "must preserve one runtime and maintenance pool connection for heartbeats"
        ),
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
    AGENT_RUN_MAX_CONCURRENT_TURNS: int = Field(
        default=11,
        ge=1,
        description="Maximum interactive agent turns admitted concurrently per API process.",
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
    NATIVE_RUN_CODE_MAX_INPUT_BYTES: int = Field(
        default=2 * 1024 * 1024,
        ge=1,
        le=20 * 1024 * 1024,
        description="Maximum combined UTF-8 workspace-file bytes inlined into run_code.",
    )
    NATIVE_RUN_CODE_MAX_UPLOAD_BYTES: int = Field(
        default=50 * 1024 * 1024,
        ge=1,
        le=100 * 1024 * 1024,
        description="Maximum source bytes accepted for one run_code workspace input.",
    )
    NATIVE_RUN_CODE_MAX_TOTAL_UPLOAD_BYTES: int = Field(
        default=100 * 1024 * 1024,
        ge=1,
        le=500 * 1024 * 1024,
        description="Maximum combined source bytes accepted by one run_code invocation.",
    )
    NATIVE_RUN_CODE_OUTPUT_MAX_CHARS: int = Field(
        default=16_000,
        ge=256,
        description="Maximum helper answer characters returned by run_code.",
    )
    NATIVE_RUN_CODE_MAX_OUTPUT_FILES: int = Field(
        default=25,
        ge=1,
        le=50,
        description=(
            "Maximum generated sandbox files persisted by one run_code call. The default covers "
            "document source, final deliverables, notes, and rendered previews."
        ),
    )
    NATIVE_RUN_CODE_MAX_OUTPUT_BYTES: int = Field(
        default=200 * 1024 * 1024,
        ge=1024 * 1024,
        le=500 * 1024 * 1024,
        description=(
            "Maximum combined generated sandbox-output bytes retrieved by one run_code call, "
            "enforced during provider download."
        ),
    )
    NATIVE_RUN_CODE_TIMEOUT_SECONDS: float = Field(
        default=600.0,
        gt=0,
        le=3600,
        description="Wall-clock timeout for one run_code invocation, including output retrieval.",
    )
    NATIVE_RUN_CODE_MAX_STEPS: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum model requests for one provider-native code-execution helper run.",
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

    @model_validator(mode="after")
    def warn_when_turn_limit_exceeds_pool_headroom(self):
        """Warns when turn concurrency exceeds the runtime pool sizing rule."""
        pool_headroom_limit = self.DB_POOL_SIZE + self.DB_POOL_MAX_OVERFLOW - 4
        if pool_headroom_limit < self.AGENT_RUN_MAX_CONCURRENT_TURNS:
            logger.warning(
                "AGENT_RUN_MAX_CONCURRENT_TURNS exceeds DB_POOL_SIZE + "
                "DB_POOL_MAX_OVERFLOW - 4; agent turns may exhaust runtime database headroom",
                extra={
                    "agent_run_max_concurrent_turns": self.AGENT_RUN_MAX_CONCURRENT_TURNS,
                    "runtime_pool_headroom_limit": pool_headroom_limit,
                },
            )
        return self

    @model_validator(mode="after")
    def validate_worker_limit_preserves_pool_headroom(self):
        """Reject worker concurrency that can block lease heartbeats behind handlers."""
        runtime_capacity = self.DB_POOL_SIZE + self.DB_POOL_MAX_OVERFLOW
        maintenance_capacity = self.DB_MAINTENANCE_POOL_SIZE + self.DB_MAINTENANCE_POOL_MAX_OVERFLOW
        worker_pool_limit = min(runtime_capacity, maintenance_capacity) - 1
        if worker_pool_limit < self.WORKER_MAX_CONCURRENT_RUNS:
            raise ValueError(
                "WORKER_MAX_CONCURRENT_RUNS must not exceed the smaller runtime or "
                "maintenance database pool capacity minus one; this preserves a "
                "connection for lease heartbeats"
            )
        return self
