# apps/api/utils/metadata.py

"""Small coercion helpers for untrusted metadata blobs."""

from uuid import UUID


def metadata_str(value: object) -> str | None:
    """Return a non-empty string metadata value, otherwise ``None``."""
    return value if isinstance(value, str) and value else None


def metadata_uuid(value: object) -> UUID | None:
    """Return a UUID metadata value parsed from common stored forms."""
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
