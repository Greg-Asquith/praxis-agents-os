# apps/api/core/settings/jobs.py

"""Generic background job worker settings."""

from pydantic import Field


class JobsSettingsMixin:
    JOBS_WORKER_POLL_SECONDS: float = Field(
        default=5.0,
        gt=0,
        description="Seconds between generic job worker polling passes.",
    )
    JOBS_WORKER_BATCH_SIZE: int = Field(
        default=10,
        gt=0,
        description="Maximum jobs claimed by one worker polling pass.",
    )
    JOBS_LOCK_TTL_SECONDS: int = Field(
        default=300,
        gt=0,
        description="Seconds before a running job lease can be reclaimed.",
    )
    JOBS_HANDLER_TIMEOUT_SECONDS: float = Field(
        default=600.0,
        gt=0,
        description="Default maximum seconds a job handler may run.",
    )
    JOBS_DEFAULT_MAX_ATTEMPTS: int = Field(
        default=5,
        gt=0,
        description="Default maximum execution attempts before a job fails terminally.",
    )
    JOBS_RETRY_BACKOFF_BASE_SECONDS: int = Field(
        default=30,
        gt=0,
        description="Base seconds for exponential retry backoff.",
    )
    JOBS_RETRY_BACKOFF_CAP_SECONDS: int = Field(
        default=3600,
        gt=0,
        description="Maximum seconds for retry backoff.",
    )
    JOBS_TERMINAL_RETENTION_DAYS: int = Field(
        default=30,
        gt=0,
        description="Days to retain terminal job rows before hard deletion.",
    )
    JOBS_SWEEP_INTERVAL_SECONDS: int = Field(
        default=3600,
        gt=0,
        description="Seconds between terminal job retention sweeps.",
    )
    JOBS_WORKSPACE_CONCURRENCY_LIMIT: int = Field(
        default=4,
        gt=0,
        description="Observed in-flight job concurrency warning threshold per workspace.",
    )
