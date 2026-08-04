# apps/api/services/security/ensure_application_encryption_keys_loaded.py

"""Load the application encryption key ring from its configured source."""

import asyncio

from pydantic import SecretStr, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import CustomValueError
from core.settings import settings
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference
from utils.security import configure_application_encryption_keys

_loaded_keys: tuple[str, ...] | None = None
_load_lock = asyncio.Lock()


async def ensure_application_encryption_keys_loaded(db: AsyncSession) -> tuple[str, ...]:
    """Resolve and cache the newest-first application encryption key ring."""
    global _loaded_keys

    if _loaded_keys is not None:
        return _loaded_keys
    async with _load_lock:
        if _loaded_keys is not None:
            return _loaded_keys

        keys = settings.application_encryption_keys
        if not keys:
            secret_name = settings.ENCRYPTION_KEYS_SECRET_NAME
            if secret_name is None:
                raise CustomValueError("Application encryption key ring is not configured")
            raw_keys = await resolve_secret(
                db,
                SecretReference(
                    provider=settings.SECRET_PROVIDER,
                    name=secret_name,
                    version="latest",
                ),
            )
            keys = _parse_secret_key_ring(raw_keys)

        configure_application_encryption_keys(keys)
        _loaded_keys = keys
        return keys


def _parse_secret_key_ring(raw_keys: str) -> tuple[str, ...]:
    """Parse and validate the provider-neutral comma/JSON secret payload."""
    parsed = settings.parse_encryption_keys(raw_keys)
    validated = settings.validate_encryption_keys(
        TypeAdapter(list[SecretStr]).validate_python(parsed)
    )
    if not validated:
        raise CustomValueError("Application encryption key ring cannot be empty")
    return tuple(entry.get_secret_value() for entry in validated)


def _reset_application_encryption_key_cache() -> None:
    """Clear process state for deterministic settings and rotation tests."""
    global _loaded_keys
    _loaded_keys = None
