# apps/api/core/request_paths.py

"""Safe request-path representations for logs, audits, and bounded keys."""

from core.settings import settings

_ARTIFACT_SHARE_PREFIX = "/artifacts/shared/"
_ARTIFACT_SHARE_TEMPLATE = "/artifacts/shared/{token}"
# Deployment routes that a link token opens. Every path below it shares one rate-limit key.
_CUSTOM_PUBLIC_PREFIX = f"{settings.API_V1_PREFIX}/custom/public/"
_CUSTOM_PUBLIC_TEMPLATE = f"{settings.API_V1_PREFIX}/custom/public/{{token}}"


def redact_capability_path(path: str) -> str:
    """Replace path-carried capability secrets with their route template."""
    if path.startswith(_ARTIFACT_SHARE_PREFIX):
        return _ARTIFACT_SHARE_TEMPLATE
    if path.startswith(_CUSTOM_PUBLIC_PREFIX):
        return _CUSTOM_PUBLIC_TEMPLATE
    return path


def is_custom_public_path(path: str) -> bool:
    """Checks whether a link token opens the path."""
    return path.startswith(_CUSTOM_PUBLIC_PREFIX)
