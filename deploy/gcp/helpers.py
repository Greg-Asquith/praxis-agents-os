#!/usr/bin/env python3
"""Small, dependency-free helpers used by the GCP deployment scripts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

AUDIT_SERVICES = (
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "cloudsql.googleapis.com",
)
AUDIT_LOG_TYPES = ("ADMIN_READ", "DATA_READ", "DATA_WRITE")
PRIVILEGED_ROLES = ("roles/owner", "roles/editor")
GCS_BROWSER_CORS_METHODS = ("GET", "HEAD", "PUT")
GCS_BROWSER_CORS_RESPONSE_HEADERS = (
    "Content-Length",
    "Content-Type",
    "ETag",
    "x-goog-generation",
    "x-goog-if-generation-match",
)
GCS_BROWSER_CORS_MAX_AGE_SECONDS = 3600


_LOGICAL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_/-]{1,255}$")
_TEMPLATE_VARIABLE_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def cloud_secret_id(name: str) -> str:
    """Mirror apps/api/services/secrets/utils.py::cloud_secret_id."""
    if not _LOGICAL_NAME_PATTERN.fullmatch(name) or name.startswith("/") or "//" in name:
        raise ValueError("invalid logical secret name")
    return f"praxis-{hashlib.sha256(name.encode('utf-8')).hexdigest()}"


def add_data_access_audit_configs(policy: dict[str, Any]) -> dict[str, Any]:
    """Merge the required Data Access audit types without touching bindings."""
    configs = list(policy.get("auditConfigs") or [])
    by_service = {config.get("service"): config for config in configs}
    for service in AUDIT_SERVICES:
        config = by_service.get(service)
        if config is None:
            config = {"service": service, "auditLogConfigs": []}
            configs.append(config)
            by_service[service] = config
        log_configs = list(config.get("auditLogConfigs") or [])
        existing = {entry.get("logType") for entry in log_configs}
        for log_type in AUDIT_LOG_TYPES:
            if log_type not in existing:
                log_configs.append({"logType": log_type})
        config["auditLogConfigs"] = log_configs
    policy["auditConfigs"] = configs
    return policy


def privileged_members(policy: dict[str, Any], members: list[str]) -> list[str]:
    """Return the given members that hold a project Owner or Editor binding."""
    held: set[str] = set()
    for binding in policy.get("bindings") or []:
        if binding.get("role") in PRIVILEGED_ROLES:
            held.update(binding.get("members") or [])
    return [member for member in members if member in held]


def gcs_browser_cors_config(origins_csv: str) -> list[dict[str, object]]:
    """Build the explicit-origin CORS policy used by browser signed URLs."""
    origins = list(
        dict.fromkeys(
            origin.strip() for origin in origins_csv.split(",") if origin.strip()
        )
    )
    if not origins:
        raise ValueError("at least one GCS browser CORS origin is required")
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError(f"invalid GCS browser CORS origin: {origin!r}")
    normalized_origins = list(dict.fromkeys(origin.rstrip("/") for origin in origins))
    return [
        {
            "origin": normalized_origins,
            "method": list(GCS_BROWSER_CORS_METHODS),
            "responseHeader": list(GCS_BROWSER_CORS_RESPONSE_HEADERS),
            "maxAgeSeconds": GCS_BROWSER_CORS_MAX_AGE_SECONDS,
        }
    ]


def render_template(template: str, values: dict[str, str], allowed: list[str]) -> str:
    """Substitute only allowlisted ${VAR} references; every allowed value is required."""
    missing = [name for name in allowed if not values.get(name)]
    if missing:
        raise ValueError(f"template variables unset or empty: {', '.join(missing)}")
    allowed_set = set(allowed)

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return values[name] if name in allowed_set else match.group(0)

    return _TEMPLATE_VARIABLE_PATTERN.sub(replace, template)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    secret_id_parser = subparsers.add_parser("secret-id")
    secret_id_parser.add_argument("logical_name")

    audit_parser = subparsers.add_parser("audit-policy")
    audit_parser.add_argument("input", type=Path)
    audit_parser.add_argument("output", type=Path)

    privileged_parser = subparsers.add_parser("privileged-members")
    privileged_parser.add_argument("input", type=Path)
    privileged_parser.add_argument("members", nargs="+")

    cors_parser = subparsers.add_parser("storage-cors")
    cors_parser.add_argument("origins")
    cors_parser.add_argument("output", type=Path)

    render_parser = subparsers.add_parser("render-template")
    render_parser.add_argument("input", type=Path)
    render_parser.add_argument("output", type=Path)
    render_parser.add_argument("allowlist", help="space-separated ${VAR} references")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.command == "secret-id":
        print(cloud_secret_id(args.logical_name))
        return

    if args.command == "render-template":
        allowed = _TEMPLATE_VARIABLE_PATTERN.findall(args.allowlist)
        template = args.input.read_text(encoding="utf-8")
        try:
            rendered = render_template(template, dict(os.environ), allowed)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc
        args.output.write_text(rendered, encoding="utf-8")
        return

    if args.command == "storage-cors":
        try:
            config = gcs_browser_cors_config(args.origins)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc
        args.output.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        return

    policy = json.loads(args.input.read_text(encoding="utf-8"))
    if args.command == "privileged-members":
        offenders = privileged_members(policy, args.members)
        for member in offenders:
            print(member)
        if offenders:
            raise SystemExit(1)
        return

    original_audit_configs = copy.deepcopy(policy.get("auditConfigs") or [])
    rendered = add_data_access_audit_configs(policy)
    args.output.write_text(json.dumps(rendered, indent=2) + "\n", encoding="utf-8")
    print("changed" if rendered.get("auditConfigs") != original_audit_configs else "unchanged")


if __name__ == "__main__":
    main()
