# apps/api/tests/services/jobs/test_job_registry.py

"""Tests for generic job registry and utility helpers."""

import pytest
from sqlalchemy.exc import IntegrityError

from services.jobs.registry import JOB_HANDLERS, job_handler
from services.jobs.utils import (
    compute_content_hash,
    is_jobs_in_flight_integrity_error,
    retry_backoff,
)


def test_job_handler_registers_and_duplicate_raises() -> None:
    kind = "tests.registry"

    async def handler(_db, _job) -> None:
        return None

    try:
        decorated = job_handler(kind=kind, timeout=1.0, max_attempts=2)(handler)

        assert decorated is handler
        assert JOB_HANDLERS[kind].function is handler
        assert JOB_HANDLERS[kind].timeout == 1.0
        assert JOB_HANDLERS[kind].max_attempts == 2
        with pytest.raises(RuntimeError, match="Duplicate"):
            job_handler(kind=kind)(handler)
    finally:
        JOB_HANDLERS.pop(kind, None)


@pytest.mark.parametrize("kind", ["Test.upper", "bad-kind", "1bad", ""])
def test_job_handler_rejects_invalid_kind(kind: str) -> None:
    async def handler(_db, _job) -> None:
        return None

    with pytest.raises(RuntimeError, match="Invalid job kind"):
        job_handler(kind=kind)(handler)


def test_job_handler_rejects_sync_function() -> None:
    kind = "tests.sync"

    def handler(_db, _job) -> None:
        return None

    try:
        with pytest.raises(RuntimeError, match="must be async"):
            job_handler(kind=kind)(handler)
    finally:
        JOB_HANDLERS.pop(kind, None)


def test_content_hash_is_key_order_independent() -> None:
    assert compute_content_hash({"b": 2, "a": 1}) == compute_content_hash({"a": 1, "b": 2})


def test_retry_backoff_grows_caps_and_jitters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.jobs.utils.random.uniform", lambda _a, _b: 1.0)
    monkeypatch.setattr("services.jobs.utils.settings.JOBS_RETRY_BACKOFF_BASE_SECONDS", 10)
    monkeypatch.setattr("services.jobs.utils.settings.JOBS_RETRY_BACKOFF_CAP_SECONDS", 25)

    assert retry_backoff(1) == 10
    assert retry_backoff(2) == 20
    assert retry_backoff(3) == 25


def test_jobs_in_flight_integrity_error_classifier() -> None:
    class FakeDiag:
        constraint_name = "uq_jobs_in_flight"

    class FakeOrig:
        diag = FakeDiag()

    assert is_jobs_in_flight_integrity_error(IntegrityError("insert", {}, FakeOrig()))
    assert not is_jobs_in_flight_integrity_error(IntegrityError("insert", {}, RuntimeError()))
