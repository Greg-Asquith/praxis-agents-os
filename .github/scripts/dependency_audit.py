# .github/scripts/dependency_audit.py

"""Run production dependency audits with validated, expiring exceptions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = REPOSITORY_ROOT / ".github" / "dependency-audit-allowlist.json"
PIP_AUDIT_VERSION = "2.10.1"
ECOSYSTEMS = {"python", "npm"}
# Git-pinned packages have no hash or PyPI advisories; their own dependencies are still audited.
GIT_PINNED_PACKAGES = {"data-science": ("timestral",)}
# A pin from another index carries a local version, such as `torch==2.15.0+cpu`, that PyPI
# doesn't list. Its public version is audited instead, without the other index's hashes.
LOCAL_VERSION_PIN = re.compile(r"^(?P<pin>[A-Za-z0-9._-]+==[^+\s;]+)\+[^\s;]+(?P<marker>[^\\]*)")
REQUIRED_EXCEPTION_FIELDS = {
    "ecosystem",
    "package",
    "advisory",
    "rationale",
    "owner",
    "expires",
}


class AllowlistError(ValueError):
    """Raised when the dependency-audit allowlist is invalid."""


def _non_empty_string(entry: dict[str, Any], field: str, position: int) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AllowlistError(
            f"exception {position}: {field} must be a non-empty string"
        )
    return value.strip()


def load_allowlist(path: Path = ALLOWLIST_PATH) -> dict[str, list[str]]:
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise AllowlistError(f"cannot read {path}: {exc}") from exc

    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise AllowlistError("allowlist schema_version must be 1")
    if set(document) != {"schema_version", "exceptions"}:
        raise AllowlistError(
            "allowlist must contain only schema_version and exceptions"
        )

    entries = document.get("exceptions")
    if not isinstance(entries, list):
        raise AllowlistError("allowlist exceptions must be a list")

    advisories: dict[str, list[str]] = {ecosystem: [] for ecosystem in ECOSYSTEMS}
    seen: set[tuple[str, str]] = set()
    today = datetime.now(tz=UTC).date()
    for position, raw_entry in enumerate(entries, start=1):
        if not isinstance(raw_entry, dict):
            raise AllowlistError(f"exception {position}: entry must be an object")
        if set(raw_entry) != REQUIRED_EXCEPTION_FIELDS:
            raise AllowlistError(
                f"exception {position}: fields must be {sorted(REQUIRED_EXCEPTION_FIELDS)}"
            )

        ecosystem = _non_empty_string(raw_entry, "ecosystem", position)
        if ecosystem not in ECOSYSTEMS:
            raise AllowlistError(
                f"exception {position}: ecosystem must be one of {sorted(ECOSYSTEMS)}"
            )
        _non_empty_string(raw_entry, "package", position)
        advisory = _non_empty_string(raw_entry, "advisory", position)
        _non_empty_string(raw_entry, "rationale", position)
        _non_empty_string(raw_entry, "owner", position)
        expiry_text = _non_empty_string(raw_entry, "expires", position)
        try:
            expiry = date.fromisoformat(expiry_text)
        except ValueError as exc:
            raise AllowlistError(
                f"exception {position}: expires must be an ISO date (YYYY-MM-DD)"
            ) from exc
        if expiry <= today:
            raise AllowlistError(
                f"exception {position}: {advisory} expired on {expiry.isoformat()}"
            )

        key = (ecosystem, advisory.casefold())
        if key in seen:
            raise AllowlistError(
                f"exception {position}: duplicate advisory {advisory} for {ecosystem}"
            )
        seen.add(key)
        advisories[ecosystem].append(advisory)

    return advisories


def run_python_audit(app: str, ignored_advisories: list[str]) -> None:
    """Audits a uv project's locked production dependencies under apps/<app>."""
    project_dir = REPOSITORY_ROOT / "apps" / app
    with tempfile.TemporaryDirectory(prefix="praxis-dependency-audit-") as temp_dir:
        requirements_path = Path(temp_dir) / "requirements.txt"
        subprocess.run(
            [
                "uv",
                "export",
                "--quiet",
                "--locked",
                "--no-dev",
                "--format",
                "requirements-txt",
                "--output-file",
                str(requirements_path),
                *(
                    option
                    for package in GIT_PINNED_PACKAGES.get(app, ())
                    for option in ("--no-emit-package", package)
                ),
            ],
            cwd=project_dir,
            check=True,
        )
        audits = [("--require-hashes", requirements_path)]
        hashed, public = split_local_version_pins(requirements_path.read_text())
        if public:
            requirements_path.write_text(hashed)
            public_path = Path(temp_dir) / "public-versions.txt"
            public_path.write_text(public)
            audits.append(("--no-deps", public_path))
        for mode, path in audits:
            command = [
                "uvx",
                "--from",
                f"pip-audit=={PIP_AUDIT_VERSION}",
                "pip-audit",
                "--strict",
                "--disable-pip",
                mode,
                "--requirement",
                str(path),
            ]
            for advisory in ignored_advisories:
                command.extend(("--ignore-vuln", advisory))
            subprocess.run(command, cwd=project_dir, check=True)


def split_local_version_pins(requirements: str) -> tuple[str, str]:
    """Splits exported requirements into the hashed pins and the local-version pins.

    The second part holds each local-version pin as its public version with its marker.
    """
    hashed: list[str] = []
    public: list[str] = []
    local = False
    for line in requirements.splitlines():
        # A requirement starts at the margin; its hashes follow on indented lines.
        if not line.startswith((" ", "\t")):
            match = LOCAL_VERSION_PIN.match(line)
            local = match is not None
            if match:
                public.append(f"{match['pin']}{match['marker']}".rstrip())
        if not local:
            hashed.append(line)
    return "\n".join(hashed) + "\n", "".join(f"{pin}\n" for pin in public)


def run_web_audit(ignored_advisories: list[str]) -> None:
    command = ["pnpm", "audit", "--prod", "--audit-level", "high"]
    for advisory in ignored_advisories:
        command.extend(("--ignore", advisory))
    subprocess.run(command, cwd=REPOSITORY_ROOT / "apps" / "web", check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=("api", "data-science", "web", "all"))
    args = parser.parse_args()

    try:
        allowlist = load_allowlist()
        if args.target in {"api", "all"}:
            run_python_audit("api", allowlist["python"])
        if args.target in {"data-science", "all"}:
            run_python_audit("data-science", allowlist["python"])
        if args.target in {"web", "all"}:
            run_web_audit(allowlist["npm"])
    except AllowlistError as exc:
        print(f"dependency audit configuration error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
