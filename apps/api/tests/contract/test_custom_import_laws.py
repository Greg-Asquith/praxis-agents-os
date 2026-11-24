# apps/api/tests/contract/test_custom_import_laws.py

"""Mechanical checks that keep deployment code in `custom/` apart from core."""

import ast
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
# The only core files that may import the custom package, and the one module each may name.
CUSTOM_SEAMS = {
    "routes/__init__.py": "custom.routes",
    "models/__init__.py": "custom.models",
    "services/runtime_catalogs/assemble_runtime_catalogs.py": "custom.runtime",
    "services/auth/utils.py": "custom.hooks",
    "services/auth/totp/verify_totp.py": "custom.hooks",
    "services/workspaces/create_workspace.py": "custom.hooks",
    "services/workspaces/memberships/delete_membership.py": "custom.hooks",
    "services/workspaces/memberships/update_membership.py": "custom.hooks",
}
# Deployment-owned trees: the package, its tests, and its migrations.
CUSTOM_OWNED = ("custom", "tests/custom", "alembic/versions/app")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.append(node.module)
    return values


def _core_files() -> list[Path]:
    files = [API_ROOT / "main.py"]
    for root in sorted(API_ROOT.iterdir()):
        if root.is_dir() and not root.name.startswith((".", "__")) and root.name != "custom":
            files.extend(root.rglob("*.py"))
    owned = tuple(API_ROOT / name for name in CUSTOM_OWNED)
    return [path for path in files if not any(path.is_relative_to(root) for root in owned)]


def test_core_only_imports_custom_code_through_named_seams() -> None:
    offenders = []
    for path in _core_files():
        relative = str(path.relative_to(API_ROOT))
        offenders.extend(
            (relative, value)
            for value in _imports(path)
            if (value == "custom" or value.startswith("custom."))
            and CUSTOM_SEAMS.get(relative) != value
        )
    assert offenders == []


def test_custom_code_does_not_import_provider_packages() -> None:
    offenders = [
        (str(path.relative_to(API_ROOT)), value)
        for path in (API_ROOT / "custom").rglob("*.py")
        for value in _imports(path)
        if value == "integrations" or value.startswith("integrations.")
    ]
    assert offenders == []
