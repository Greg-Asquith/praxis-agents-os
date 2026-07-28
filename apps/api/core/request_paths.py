# apps/api/core/request_paths.py

"""Safe request-path representations for logs, audits, and bounded keys."""

_ARTIFACT_SHARE_PREFIX = "/artifacts/shared/"
_ARTIFACT_SHARE_TEMPLATE = "/artifacts/shared/{token}"


def redact_capability_path(path: str) -> str:
    """Replace path-carried capability secrets with their route template."""
    if path.startswith(_ARTIFACT_SHARE_PREFIX):
        return _ARTIFACT_SHARE_TEMPLATE
    return path
