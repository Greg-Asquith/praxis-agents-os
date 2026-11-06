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


def _check_isolated_service(document: dict[str, Any], name: str) -> None:
    # Ingress is open because there is no VPC, so invoker IAM must stay on.
    annotations = document["metadata"]["annotations"]
    if "run.googleapis.com/invoker-iam-disabled" in annotations:
        raise ValueError(f"{name} must keep invoker IAM enabled")
    template = document["spec"]["template"]
    if template["spec"]["containerConcurrency"] != 1:
        raise ValueError(f"{name} must handle one request per instance")
    timeout = template["spec"]["timeoutSeconds"]
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        raise TypeError(f"{name} timeoutSeconds must be an integer, got {timeout!r}")
    if not isinstance(template["metadata"]["annotations"]["autoscaling.knative.dev/maxScale"], str):
        raise TypeError(f"{name} maxScale must render as a string")
    env_names = {entry["name"] for entry in template["spec"]["containers"][0]["env"]}
    if any(not env_name.startswith("RENDERER_") for env_name in env_names):
        raise ValueError(f"{name} must receive only RENDERER_* settings")


def main() -> None:
    rendered_dir = Path(sys.argv[1])
    manifests = {
        "api": _load(rendered_dir / "services/praxis-api.yaml"),
        "web": _load(rendered_dir / "services/praxis-web.yaml"),
        "renderer": _load(rendered_dir / "services/praxis-media-renderer.yaml"),
        "data-science": _load(rendered_dir / "services/praxis-data-science.yaml"),
        "migrate": _load(rendered_dir / "jobs/praxis-migrate.yaml"),
        "worker": _load(rendered_dir / "jobs/praxis-worker.yaml"),
    }
    for name in ("api", "web", "renderer", "data-science"):
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
    _check_isolated_service(manifests["renderer"], "media renderer")
    _check_isolated_service(manifests["data-science"], "data science service")
    # Series travel inline, so the data science service must not fetch any URL.
    if "RENDERER_ALLOWED_URL_PREFIXES" in _service_env_names(manifests["data-science"]):
        raise ValueError("data science service must not allow transfer URLs")
    if "SUPER_ADMIN_EMAILS" not in _service_env_names(manifests["api"]):
        raise ValueError("API manifest does not configure the super-admin allowlist")
    if "EMAIL_AUTH_ENABLED" not in _service_env_names(manifests["api"]):
        raise ValueError("API manifest does not configure email authentication")


if __name__ == "__main__":
    main()
