"""Tests for process-level database pool settings."""

import logging

import pytest
from pydantic import ValidationError

from core.settings import Settings


def test_worker_concurrency_preserves_runtime_and_maintenance_pool_headroom() -> None:
    with pytest.raises(
        ValidationError,
        match="WORKER_MAX_CONCURRENT_RUNS must not exceed the smaller runtime or maintenance",
    ):
        Settings(
            _env_file=None,
            WORKER_MAX_CONCURRENT_RUNS=6,
            DB_POOL_SIZE=5,
            DB_POOL_MAX_OVERFLOW=10,
            DB_MAINTENANCE_POOL_SIZE=3,
            DB_MAINTENANCE_POOL_MAX_OVERFLOW=3,
        )


def test_turn_concurrency_warns_when_runtime_pool_headroom_is_too_small(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="core.settings.agents"):
        Settings(
            _env_file=None,
            AGENT_RUN_MAX_CONCURRENT_TURNS=12,
            DB_POOL_SIZE=5,
            DB_POOL_MAX_OVERFLOW=10,
        )
    record = next(
        record
        for record in caplog.records
        if record.getMessage().startswith("AGENT_RUN_MAX_CONCURRENT_TURNS exceeds")
    )
    assert record.agent_run_max_concurrent_turns == 12
    assert record.runtime_pool_headroom_limit == 11
