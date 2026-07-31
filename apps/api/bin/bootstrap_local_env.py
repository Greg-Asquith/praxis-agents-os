# apps/api/bin/bootstrap_local_env.py

"""Create the uncommitted local environment files used by every dev path."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import secrets
import shutil
from contextlib import suppress
from pathlib import Path

_HISTORICAL_PLACEHOLDER_SHA256 = "059a4896bded304276493f16cba0345208fa6bb7a72af14b1433d28e7830169b"


def _read_value(path: Path, name: str) -> str | None:
    if not path.exists():
        return None
    prefix = f"{name}="
    for line in path.read_text().splitlines():
        if line.startswith(prefix):
            value = line.removeprefix(prefix).strip()
            return value or None
    return None


def _write_value(path: Path, name: str, value: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    prefix = f"{name}="
    output: list[str] = []
    written = False
    for line in lines:
        if line.startswith(prefix):
            if not written:
                output.append(f"{prefix}{value}")
                written = True
            continue
        output.append(line)
    if not written:
        output.append(f"{prefix}{value}")
    path.write_text("\n".join(output) + "\n")


def _credential_key(paths: list[Path]) -> str:
    for path in paths:
        value = _read_value(path, "CREDENTIAL_MASTER_KEYS")
        if value and hashlib.sha256(value.encode()).hexdigest() != _HISTORICAL_PLACEHOLDER_SHA256:
            return value
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def _copy_if_missing(source: Path, destination: Path) -> bool:
    if destination.exists() and destination.stat().st_size > 0:
        return False
    shutil.copyfile(source, destination)
    return True


def _match_workspace_owner(workspace: Path, paths: list[Path]) -> None:
    owner = workspace.stat()
    for path in paths:
        with suppress(PermissionError):
            os.chown(path, owner.st_uid, owner.st_gid)


def bootstrap(workspace: Path) -> list[str]:
    api_example = workspace / "apps/api/.env.example"
    api_env = workspace / "apps/api/.env"
    generated = workspace / ".local/generated"
    targets = workspace / ".local/targets"
    data = workspace / ".local/data"
    api_generated_env = generated / "local.api.env"
    web_generated_env = generated / "local.web.env"
    secrets_env = targets / "local.secrets.env"

    created: list[str] = []
    for directory in (generated, targets, data / "storage"):
        directory.mkdir(parents=True, exist_ok=True)

    if _copy_if_missing(api_example, api_env):
        created.append(str(api_env.relative_to(workspace)))
    if _copy_if_missing(api_example, api_generated_env):
        created.append(str(api_generated_env.relative_to(workspace)))

    key = _credential_key([api_env, api_generated_env])
    for path in (api_env, api_generated_env):
        _write_value(path, "CREDENTIAL_MASTER_KEYS", key)
        _write_value(path, "ARTIFACT_SHARING_ENABLED", "true")

    if not web_generated_env.exists():
        web_generated_env.write_text("VITE_API_BASE_URL=http://localhost:8000/api/v1\n")
        created.append(str(web_generated_env.relative_to(workspace)))

    if not secrets_env.exists():
        secrets_env.touch(mode=0o600)
        created.append(str(secrets_env.relative_to(workspace)))
    secrets_env.chmod(0o600)

    _match_workspace_owner(
        workspace,
        [
            generated,
            targets,
            data,
            data / "storage",
            api_env,
            api_generated_env,
            web_generated_env,
            secrets_env,
        ],
    )
    return created


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    created = bootstrap(workspace)
    if created:
        print("Created local environment:")
        for path in created:
            print(f"  {path}")
    else:
        print("Local environment is ready.")


if __name__ == "__main__":
    main()
