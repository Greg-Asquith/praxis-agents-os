"""Clean-process import smoke tests for deployed API and worker entrypoints."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "statement",
    (
        "from main import app",
        "import workers.main",
    ),
)
def test_deployment_entrypoint_imports_in_clean_process(statement: str) -> None:
    result = subprocess.run(  # noqa: S603 - fixed interpreter and audited statements
        [sys.executable, "-c", statement],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
