# deploy/gcp/tests/validate_manifests.py
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


def _check_renderer(document: dict[str, Any]) -> None:
    # Ingress is open because there is no VPC, so invoker IAM must stay on.
    annotations = document["metadata"]["annotations"]
    if "run.googleapis.com/invoker-iam-disabled" in annotations:
        raise ValueError("media renderer must keep invoker IAM enabled")
    template = document["spec"]["template"]
    if template["spec"]["containerConcurrency"] != 1:
        raise ValueError("media renderer must handle one request per instance")
    timeout = template["spec"]["timeoutSeconds"]
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        raise TypeError(f"media renderer timeoutSeconds must be an integer, got {timeout!r}")
    if not isinstance(template["metadata"]["annotations"]["autoscaling.knative.dev/maxScale"], str):
        raise TypeError("media renderer maxScale must render as a string")
    env_names = {entry["name"] for entry in template["spec"]["containers"][0]["env"]}
    if any(not name.startswith("RENDERER_") for name in env_names):
        raise ValueError("media renderer must receive only RENDERER_* settings")


def main() -> None:
    rendered_dir = Path(sys.argv[1])
    manifests = {
        "api": _load(rendered_dir / "services/praxis-api.yaml"),
        "web": _load(rendered_dir / "services/praxis-web.yaml"),
        "renderer": _load(rendered_dir / "services/praxis-media-renderer.yaml"),
        "migrate": _load(rendered_dir / "jobs/praxis-migrate.yaml"),
        "worker": _load(rendered_dir / "jobs/praxis-worker.yaml"),
    }
    for name in ("api", "web", "renderer"):
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
    _check_renderer(manifests["renderer"])
    if "SUPER_ADMIN_EMAILS" not in _service_env_names(manifests["api"]):
        raise ValueError("API manifest does not configure the super-admin allowlist")
    if "EMAIL_AUTH_ENABLED" not in _service_env_names(manifests["api"]):
        raise ValueError("API manifest does not configure email authentication")


if __name__ == "__main__":
    main()
