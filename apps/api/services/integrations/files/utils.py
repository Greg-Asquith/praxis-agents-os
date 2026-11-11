# apps/api/services/integrations/files/utils.py

"""Approval pins for workspace File sources that integration tools send to a provider."""

from collections.abc import Mapping
from typing import Any

from core.exceptions.integration import IntegrationValidationError

_PINNED_FIELDS = ("file_id", "revision_id", "content_hash")
_CHANGED = "The File changed after it was approved. Ask the agent to prepare the upload again."
_UNAVAILABLE = "The File's content is unavailable. Choose another File or upload it again."


def source_changed_error(*, provider_key: str, operation: str) -> IntegrationValidationError:
    """Builds the error for a File that isn't the revision the approver saw."""
    return IntegrationValidationError(
        _CHANGED, provider_key=provider_key, operation=operation, error_code="source_changed"
    )


def source_unavailable_error(*, provider_key: str, operation: str) -> IntegrationValidationError:
    """Builds the error for a File whose stored content is missing."""
    return IntegrationValidationError(
        _UNAVAILABLE,
        provider_key=provider_key,
        operation=operation,
        error_code="source_unavailable",
    )


def pinned_files(reviewed: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Returns the approval's `_files` pins by File ID."""
    files = reviewed.get("_files")
    if not isinstance(files, list):
        return {}
    return {str(item.get("file_id")): item for item in files if isinstance(item, Mapping)}


def require_pinned_file(
    details: Mapping[str, Any],
    pinned: Mapping[str, Any] | None,
    *,
    provider_key: str,
    operation: str,
) -> None:
    """Fails when the File's current revision isn't the one the approver saw."""
    if pinned is None or any(pinned.get(key) != details[key] for key in _PINNED_FIELDS):
        raise source_changed_error(provider_key=provider_key, operation=operation)
