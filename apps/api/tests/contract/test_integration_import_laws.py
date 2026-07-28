"""Mechanical provider-package dependency-direction checks."""

import ast
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_PROVIDER_SERVICE_PREFIXES = (
    "services.agents.runtime.context",
    "services.agents.runtime.tools",
    "services.agents.runtime.untrusted",
    "services.audit_events",
    "services.integrations",
    "services.jobs.registry",
    "services.secrets",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.append(node.module)
    return values


PROVIDER_IMPORT_EXEMPT_PATHS = ("services/integrations/loader.py",)


def test_core_only_imports_provider_packages_through_loader() -> None:
    offenders = []
    roots = ("services", "routes", "models", "workers", "core")
    exempt = {API_ROOT / exempt_path for exempt_path in PROVIDER_IMPORT_EXEMPT_PATHS}
    for root in roots:
        for path in (API_ROOT / root).rglob("*.py"):
            if path in exempt:
                continue
            if any(value.startswith("integrations.") for value in _imports(path)):
                offenders.append(str(path.relative_to(API_ROOT)))
    assert offenders == []


def test_provider_packages_do_not_import_each_other() -> None:
    offenders = []
    for path in (API_ROOT / "integrations").rglob("*.py"):
        own_key = path.relative_to(API_ROOT / "integrations").parts[0]
        offenders.extend(
            (str(path.relative_to(API_ROOT)), value)
            for value in _imports(path)
            if value.startswith("integrations.") and not value.startswith(f"integrations.{own_key}")
        )
    assert offenders == []


def test_provider_packages_only_import_published_service_seams() -> None:
    offenders = []
    for path in (API_ROOT / "integrations").rglob("*.py"):
        offenders.extend(
            (str(path.relative_to(API_ROOT)), value)
            for value in _imports(path)
            if value.startswith("services.")
            and not value.startswith(ALLOWED_PROVIDER_SERVICE_PREFIXES)
        )
    assert offenders == []
