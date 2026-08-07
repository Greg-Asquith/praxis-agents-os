from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError(f"{path} did not render to a YAML mapping")
    return document


def _service_cpu(document: dict[str, Any]) -> object:
    return document["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"][
        "cpu"
    ]


def _job_cpu(document: dict[str, Any]) -> object:
    return document["spec"]["template"]["spec"]["template"]["spec"]["containers"][0][
        "resources"
    ]["limits"]["cpu"]


def _job_task_spec(document: dict[str, Any]) -> dict[str, Any]:
    return document["spec"]["template"]["spec"]["template"]["spec"]


def _service_env_names(document: dict[str, Any]) -> set[str]:
    container = document["spec"]["template"]["spec"]["containers"][0]
    return {entry["name"] for entry in container.get("env") or []}


def main() -> None:
    rendered_dir = Path(sys.argv[1])
    manifests = {
        "api": _load(rendered_dir / "services/praxis-api.yaml"),
        "web": _load(rendered_dir / "services/praxis-web.yaml"),
        "migrate": _load(rendered_dir / "jobs/praxis-migrate.yaml"),
        "worker": _load(rendered_dir / "jobs/praxis-worker.yaml"),
    }
    for name in ("api", "web"):
        cpu = _service_cpu(manifests[name])
        if not isinstance(cpu, str):
            raise TypeError(f"{name} CPU limit must render as a string, got {cpu!r}")
    for name in ("migrate", "worker"):
        cpu = _job_cpu(manifests[name])
        if not isinstance(cpu, str):
            raise TypeError(f"{name} CPU limit must render as a string, got {cpu!r}")
        task_spec = _job_task_spec(manifests[name])
        for field in ("timeoutSeconds", "maxRetries"):
            value = task_spec[field]
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} {field} must render as an integer, got {value!r}")
    for name in ("api", "web"):
        if "PORT" in _service_env_names(manifests[name]):
            raise ValueError(f"{name} sets PORT, a reserved Cloud Run env name")
    if "SUPER_ADMIN_EMAILS" not in _service_env_names(manifests["api"]):
        raise ValueError("API manifest does not configure the super-admin allowlist")
    if "EMAIL_AUTH_ENABLED" not in _service_env_names(manifests["api"]):
        raise ValueError("API manifest does not configure email authentication")


if __name__ == "__main__":
    main()
