# apps/media-renderer/tests/conftest.py

"""Serves the media fixtures through the driver's fake signed-URL storage."""

from pathlib import Path

import pytest

pytest_plugins = ["driver_testing.plugin"]


@pytest.fixture
def storage_fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
