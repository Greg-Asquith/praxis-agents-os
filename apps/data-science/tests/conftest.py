# apps/data-science/tests/conftest.py

import pytest
from driver.server import DriverConfig

pytest_plugins = ["driver_testing.plugin"]


@pytest.fixture
def config(config: DriverConfig) -> DriverConfig:
    # PyTorch and the model's weights need the child memory the service runs with.
    return DriverConfig(**{**config.__dict__, "child_memory_bytes": 3 * 1024**3})
