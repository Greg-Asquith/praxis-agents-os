"""Tests for process-level database pool settings."""

import logging
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

import core.database as database_module
from core.settings import Settings, settings


def test_connection_pool_settings_have_bounded_defaults() -> None:
    resolved = Settings(_env_file=None)

    assert resolved.AGENT_RUN_MAX_CONCURRENT_TURNS == 11
    assert resolved.DB_MAINTENANCE_POOL_SIZE == 3
    assert resolved.DB_MAINTENANCE_POOL_MAX_OVERFLOW == 3


def test_default_turn_concurrency_preserves_runtime_pool_headroom(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="core.settings.agents"):
        Settings(_env_file=None)

    assert not any(
        record.getMessage().startswith("AGENT_RUN_MAX_CONCURRENT_TURNS exceeds")
        for record in caplog.records
    )


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


def test_maintenance_engine_uses_its_dedicated_pool_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = Mock()
    create_engine = Mock(return_value=sentinel)
    monkeypatch.setattr(database_module, "_maintenance_async_engine", None)
    monkeypatch.setattr(database_module, "create_async_engine", create_engine)
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "DB_MAINTENANCE_POOL_SIZE", 7)
    monkeypatch.setattr(settings, "DB_MAINTENANCE_POOL_MAX_OVERFLOW", 2)

    assert database_module.get_maintenance_async_engine() is sentinel
    _url, kwargs = create_engine.call_args
    assert kwargs["pool_size"] == 7
    assert kwargs["max_overflow"] == 2
