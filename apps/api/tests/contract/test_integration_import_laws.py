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


def test_provider_packages_do_not_recreate_shared_operation_process_helpers() -> None:
    forbidden = {
        "fan_out_dict",
        "record_airtable_operation_audit",
        "record_gmail_operation_audit",
        "record_google_ads_operation_audit",
        "run_audited_operation",
    }
    offenders = []
    for path in (API_ROOT / "integrations").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(
            (str(path.relative_to(API_ROOT)), node.name)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden
        )
    assert offenders == []


def test_representative_simple_writes_use_the_published_recipe() -> None:
    paths = (
        "integrations/gmail/tools/send_message.py",
        "integrations/airtable/tools/create_record.py",
        "integrations/airtable/tools/update_record.py",
    )
    forbidden = (
        "on_write_denied",
        "record_integration_operation_audit_event",
        "require_durable_audit",
        "serialize_fan_out_results(item)",
    )
    for relative_path in paths:
        source = (API_ROOT / relative_path).read_text(encoding="utf-8")
        assert "run_audited_integration_operation" in source
        assert "pending_operation_detail=" in source
        assert "serialize_fan_out_results(results)" in source
        assert all(value not in source for value in forbidden)
