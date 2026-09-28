"""Clean-process import smoke test for deployed API and worker entrypoints."""

import subprocess
import sys


def test_entrypoints_import_without_assembling_catalogs_then_assemble_idempotently() -> None:
    statement = """
from main import app
import workers.main
from services.runtime_catalogs import assemble_runtime_catalogs
from services.agents.runtime.entity_references.registry import ENTITY_RESOLVERS
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.jobs.registry import JOB_HANDLERS
from core.settings import settings
assert not ENTITY_RESOLVERS
assert not RUNTIME_TOOL_CATALOG
assert not JOB_HANDLERS
assemble_runtime_catalogs()
first_counts = (len(ENTITY_RESOLVERS), len(RUNTIME_TOOL_CATALOG), len(JOB_HANDLERS))
assemble_runtime_catalogs()
assert first_counts == (len(ENTITY_RESOLVERS), len(RUNTIME_TOOL_CATALOG), len(JOB_HANDLERS))
assert all(first_counts)
assert set(settings.INTEGRATIONS_ENABLED_PROVIDERS) == set(PROVIDER_MANIFESTS)
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and audited statement
        [sys.executable, "-c", statement],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
