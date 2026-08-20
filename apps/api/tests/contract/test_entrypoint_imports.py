"""Clean-process import smoke tests for deployed API and worker entrypoints."""

import os
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


def test_registration_free_imports_do_not_assemble_catalogs() -> None:
    statement = """
import services.agents.runtime.tools.files.utils
import services.agents.runtime.tools.native.classifier_contract
from services.agents.runtime.entity_references.registry import ENTITY_RESOLVERS
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.jobs.registry import JOB_HANDLERS
assert not ENTITY_RESOLVERS
assert not RUNTIME_TOOL_CATALOG
assert not JOB_HANDLERS
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and audited statement
        [sys.executable, "-c", statement],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "statement",
    (
        "from main import app",
        "import workers.main",
        "import workers.agent_runner",
        "import workers.job_runner",
        "import bin.application_encryption",
    ),
)
def test_entrypoint_module_imports_do_not_assemble_catalogs(statement: str) -> None:
    script = f"""
{statement}
from services.agents.runtime.entity_references.registry import ENTITY_RESOLVERS
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.jobs.registry import JOB_HANDLERS
assert not ENTITY_RESOLVERS
assert not RUNTIME_TOOL_CATALOG
assert not JOB_HANDLERS
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and audited statements
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


def test_code_mode_leaf_import_does_not_load_bridge() -> None:
    statement = """
import sys
import services.agents.runtime.code_mode.metadata
assert "services.agents.runtime.code_mode.bridge" not in sys.modules
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and audited statement
        [sys.executable, "-c", statement],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


def test_explicit_catalog_assembly_is_idempotent() -> None:
    statement = """
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
assert {
    "build_chart",
    "classify",
    "list_artifacts",
    "list_files",
    "read_todos",
    "report_completion",
    "run_workflow",
    "save_memory",
    "search_knowledge",
}.issubset(RUNTIME_TOOL_CATALOG)
assert {
    "files.extract",
    "integrations.discover_resources",
    "integrations.process_event",
}.issubset(JOB_HANDLERS)
assert {"agent", "artifact", "file", "knowledge_document", "memory"}.issubset(
    ENTITY_RESOLVERS
)
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


@pytest.mark.parametrize(
    "statement",
    (
        (
            "import asyncio; from main import app; "
            "asyncio.run(app.router.lifespan_context(app).__aenter__())"
        ),
        "import asyncio; from workers.main import main; asyncio.run(main())",
        ("import asyncio; from workers.agent_runner import main; asyncio.run(main(['--once']))"),
        ("import asyncio; from workers.job_runner import main; asyncio.run(main(['--once']))"),
        "import asyncio; from evals.run import main; asyncio.run(main())",
        ("import asyncio; from bin.application_encryption import run; asyncio.run(run('check'))"),
    ),
)
def test_deployment_entrypoints_fail_fast_for_unknown_provider(statement: str) -> None:
    env = {**os.environ, "INTEGRATIONS_ENABLED_PROVIDERS": '["does_not_exist"]'}
    result = subprocess.run(  # noqa: S603 - fixed interpreter and audited statements
        [sys.executable, "-c", statement],
        capture_output=True,
        check=False,
        env=env,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "Unknown enabled integration provider" in result.stderr


def test_catalog_assembly_repeats_the_first_failure() -> None:
    statement = """
from core.settings import settings
from services.runtime_catalogs import assemble_runtime_catalogs
settings.INTEGRATIONS_ENABLED_PROVIDERS = ["gmail", "does_not_exist"]
try:
    assemble_runtime_catalogs()
except RuntimeError as exc:
    assert "Unknown enabled integration provider" in str(exc)
else:
    raise AssertionError("first assembly unexpectedly succeeded")
try:
    assemble_runtime_catalogs()
except RuntimeError as exc:
    assert str(exc) == "Runtime catalog assembly previously failed"
    assert exc.__cause__ is not None
    assert "Unknown enabled integration provider" in str(exc.__cause__)
else:
    raise AssertionError("failed assembly unexpectedly retried")
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and audited statement
        [sys.executable, "-c", statement],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
