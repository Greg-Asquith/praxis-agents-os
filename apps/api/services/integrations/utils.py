# apps/api/services/integrations/utils.py

"""Credential-key derivation and fingerprint helpers."""

import asyncio
import base64
import hashlib
from typing import Final

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference
from utils.security import create_hmac_signature, derive_purpose_key

TOKEN_PURPOSE: Final = "praxis:credential-tokens:v1"
FINGERPRINT_PURPOSE: Final = "praxis:principal-fingerprint:v1"

_root_key_strings: tuple[str, ...] | None = None
_load_lock = asyncio.Lock()


async def ensure_credential_keys_loaded(db: AsyncSession) -> tuple[str, ...]:
    """Resolve credential roots once per process, never during module import."""
    global _root_key_strings

    if _root_key_strings is not None:
        return _root_key_strings
    async with _load_lock:
        if _root_key_strings is not None:
            return _root_key_strings
        raw_keys = settings.CREDENTIAL_MASTER_KEYS
        if settings.ENVIRONMENT != "local":
            raw_keys = await resolve_secret(
                db,
                SecretReference(
                    provider=settings.SECRET_PROVIDER,
                    name=settings.CREDENTIAL_MASTER_KEY_SECRET_NAME,
                    version="latest",
                ),
            )
        keys = tuple(value.strip() for value in (raw_keys or "").split(",") if value.strip())
        if not keys:
            raise IntegrationAuthError(
                "Credential master key is not configured",
                provider_key=settings.SECRET_PROVIDER,
                operation="load_credential_keys",
            )
        for value in keys:
            try:
                Fernet(value.encode("ascii"))
            except Exception as exc:
                raise IntegrationAuthError(
                    "Credential master key is invalid",
                    provider_key=settings.SECRET_PROVIDER,
                    operation="load_credential_keys",
                    original_error=exc,
                ) from exc
        _root_key_strings = keys
        return keys


def credential_encryption_key_id() -> str:
    return hashlib.sha256(_newest_root_key().encode("ascii")).hexdigest()[:16]


def encrypt_credential_token(value: str) -> str:
    return _credential_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_credential_token(value: str) -> str:
    return _credential_fernet().decrypt(value.encode("ascii")).decode("utf-8")


def compute_principal_fingerprint(provider_key: str, external_principal_id: str) -> str:
    root = _decoded_root(_newest_root_key())
    key = derive_purpose_key(root, FINGERPRINT_PURPOSE).hex()
    return create_hmac_signature(f"{provider_key}:{external_principal_id}", key)


def _credential_fernet() -> MultiFernet:
    instances = []
    for root_key in _loaded_root_keys():
        derived = derive_purpose_key(_decoded_root(root_key), TOKEN_PURPOSE)
        instances.append(Fernet(base64.urlsafe_b64encode(derived)))
    return MultiFernet(instances)


def _decoded_root(root_key: str) -> bytes:
    return base64.urlsafe_b64decode(root_key.encode("ascii"))


def _newest_root_key() -> str:
    return _loaded_root_keys()[0]


def _loaded_root_keys() -> tuple[str, ...]:
    if _root_key_strings is None:
        raise IntegrationAuthError(
            "Credential keys must be loaded before token access",
            provider_key=settings.SECRET_PROVIDER,
            operation="credential_crypto",
        )
    return _root_key_strings


def _reset_credential_key_cache() -> None:
    """Clear process state for deterministic settings and rotation tests."""
    global _root_key_strings
    _root_key_strings = None


async def record_integration_audit(
    db: AsyncSession,
    *,
    workspace_id: object | None,
    action: object,
    resource_type: object,
    resource_id: object | None,
    details: dict[str, object],
    status: object | None = None,
) -> None:
    """Record a service-authored integration event through the safe audit seam."""
    from services.audit_events import (
        AuditActorType,
        AuditStatus,
        safe_record_operation_audit_event,
    )

    kwargs = {
        "workspace_id": workspace_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "actor_type": AuditActorType.SERVICE,
        "actor_display": "integration-service",
        "details": details,
    }
    if status is not None:
        kwargs["status"] = status
    else:
        kwargs["status"] = AuditStatus.SUCCESS
    await safe_record_operation_audit_event(db, **kwargs)
