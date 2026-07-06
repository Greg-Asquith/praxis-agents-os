# apps/api/services/storage/paths.py

"""Provider-neutral object key and HTTP header helpers."""

from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import uuid4

from services.storage.errors import StorageValidationError

MAX_OBJECT_KEY_LENGTH = 1024


def validate_object_key(object_key: str) -> str:
    """Validate a provider-neutral object key.

    Object keys are POSIX-style relative paths. They are intentionally stricter
    than cloud object stores so every provider shares the same traversal safety
    rules.
    """
    if not isinstance(object_key, str):
        raise StorageValidationError(
            "Storage object key must be a string", operation="validate_key"
        )

    if object_key != object_key.strip():
        raise StorageValidationError(
            "Storage object key cannot start or end with whitespace",
            operation="validate_key",
            object_key=object_key,
        )

    if not object_key:
        raise StorageValidationError("Storage object key is required", operation="validate_key")

    if len(object_key) > MAX_OBJECT_KEY_LENGTH:
        raise StorageValidationError(
            "Storage object key is too long",
            operation="validate_key",
            object_key=object_key,
        )

    if object_key.startswith("/") or object_key.endswith("/"):
        raise StorageValidationError(
            "Storage object key must be a relative file path",
            operation="validate_key",
            object_key=object_key,
        )

    if "\\" in object_key or "\x00" in object_key:
        raise StorageValidationError(
            "Storage object key contains an invalid character",
            operation="validate_key",
            object_key=object_key,
        )

    parts = object_key.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise StorageValidationError(
            "Storage object key contains an invalid path segment",
            operation="validate_key",
            object_key=object_key,
        )

    if any(any(ord(char) < 32 for char in part) for part in parts):
        raise StorageValidationError(
            "Storage object key contains a control character",
            operation="validate_key",
            object_key=object_key,
        )

    return object_key


def quote_object_key(object_key: str) -> str:
    """URL-encode an object key while preserving path separators."""
    return "/".join(quote(part, safe="") for part in validate_object_key(object_key).split("/"))


def build_content_disposition(filename: str | None) -> str | None:
    """Build an attachment Content-Disposition header."""
    if not filename:
        return None

    sanitized = filename.replace("\r", "").replace("\n", "").replace('"', "_")
    try:
        sanitized.encode("ascii")
        return f'attachment; filename="{sanitized}"'
    except UnicodeEncodeError:
        ascii_fallback = sanitized.encode("ascii", "replace").decode("ascii").replace("?", "_")
        encoded = quote(sanitized, safe="")
        return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


def safe_filename(filename: str, *, fallback: str = "file") -> str:
    """Return a filesystem-neutral filename segment for generated object keys."""
    candidate = filename.replace("\\", "/").split("/")[-1].strip()
    candidate = "".join("_" if ord(char) < 32 or char in {'"', "'"} else char for char in candidate)
    return candidate or fallback


def unique_object_key(prefix: str, filename: str) -> str:
    """Build a unique object key under an existing prefix."""
    clean_prefix = validate_object_key(prefix.rstrip("/"))
    clean_filename = safe_filename(filename)
    suffix = PurePosixPath(clean_filename).suffix.lower()
    return validate_object_key(f"{clean_prefix}/{uuid4()}{suffix}")
