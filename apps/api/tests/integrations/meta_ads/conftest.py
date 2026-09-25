"""Isolates process-local Meta usage state between tests."""

import pytest

from integrations.meta_ads import throttle


@pytest.fixture(autouse=True)
def isolated_throttle(monkeypatch):
    monkeypatch.setattr(throttle, "_accounts", {})
