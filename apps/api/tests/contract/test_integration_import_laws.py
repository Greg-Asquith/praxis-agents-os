"""Mechanical provider-package dependency-direction checks."""

import ast
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.append(node.module)
    return values


def test_core_only_imports_provider_packages_through_loader() -> None:
    offenders = []
    roots = ("services", "routes", "models", "workers", "core")
    for root in roots:
        for path in (API_ROOT / root).rglob("*.py"):
            if path == API_ROOT / "services/integrations/loader.py":
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
