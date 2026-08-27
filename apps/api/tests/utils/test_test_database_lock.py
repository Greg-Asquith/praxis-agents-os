# apps/api/tests/utils/test_test_database_lock.py
"""Tests for cross-process test database serialization."""

import multiprocessing
from multiprocessing.synchronize import Event
from uuid import uuid4

from tests.support.database import serialize_test_database


def _acquire_database_lock(database_url: str, acquired: Event, release: Event) -> None:
    with serialize_test_database(database_url):
        acquired.set()
        release.wait(timeout=5)


def test_database_lock_serializes_pytest_processes() -> None:
    database_url = f"postgresql://localhost/praxis_lock_test_{uuid4().hex}"
    process_context = multiprocessing.get_context("spawn")
    acquired = process_context.Event()
    release = process_context.Event()
    process = process_context.Process(
        target=_acquire_database_lock,
        args=(database_url, acquired, release),
    )

    with serialize_test_database(database_url):
        process.start()
        assert not acquired.wait(timeout=0.25)

    try:
        assert acquired.wait(timeout=3)
    finally:
        release.set()
        process.join(timeout=3)
        if process.is_alive():
            process.terminate()
            process.join(timeout=3)

    assert process.exitcode == 0
