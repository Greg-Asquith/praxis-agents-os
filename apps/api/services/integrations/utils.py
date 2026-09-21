# apps/api/services/integrations/utils.py

"""Credential derivation and integration audit helpers."""

import asyncio
import base64
import hashlib
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Final, Literal
from uuid import UUID

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationFailureDisposition,
)
from core.settings import settings
from services.audit_events import (
    AuditStatus,
    IntegrationOperationDetail,
    PendingIntegrationOperationDetail,
    TerminalIntegrationOperationDetail,
)
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference
from utils.security import create_hmac_signature, derive_purpose_key

if TYPE_CHECKING:
    from services.integrations.operations import IntegrationAuditOutcome

TOKEN_PURPOSE: Final = "praxis:credential-tokens:v1"
FINGERPRINT_PURPOSE: Final = "praxis:principal-fingerprint:v1"

_TERMINAL_AUDIT_STATUSES = frozenset(
    {
        AuditStatus.SUCCESS,
        AuditStatus.PARTIAL,
        AuditStatus.FAILURE,
        AuditStatus.UNVERIFIED,
        AuditStatus.DENIED,
    }
)


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


def integration_failure_code(exc: BaseException) -> str:
    """Returns the shared public and audit code for an integration failure."""
    if getattr(exc, "failure_disposition", None) is IntegrationFailureDisposition.AMBIGUOUS:
        return "unverified_mutation"
    code = exc.error_code if isinstance(exc, IntegrationError) else None
    if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
        return code
    return exc.__class__.__name__


def validate_integration_audit_input(
    durable: bool,
    pending_operation_detail: PendingIntegrationOperationDetail | None,
    prepare_pending_operation: Callable[[], Awaitable[PendingIntegrationOperationDetail]] | None,
) -> None:
    """Validates pending intent before starting operation audit tracking."""
    if pending_operation_detail is not None and prepare_pending_operation is not None:
        raise ValueError("Pass pending operation detail directly or prepare it, not both")
    if durable and pending_operation_detail is None and prepare_pending_operation is None:
        raise ValueError("External integration writes require pending operation detail")
    if (
        durable
        and prepare_pending_operation is None
        and not isinstance(pending_operation_detail, PendingIntegrationOperationDetail)
    ):
        raise ValueError("External integration writes require pending-phase operation detail")


def validate_integration_audit_outcome[T](
    outcome: "IntegrationAuditOutcome[T]", durable: bool
) -> None:
    """Validates terminal evidence before recording an operation outcome."""
    if outcome.status not in _TERMINAL_AUDIT_STATUSES:
        raise ValueError("Integration audit outcomes must have a terminal status")
    if durable and outcome.operation_detail is None:
        raise ValueError("Successful external integration writes require terminal evidence")
    if outcome.operation_detail is not None and not isinstance(
        outcome.operation_detail, TerminalIntegrationOperationDetail
    ):
        raise ValueError("Integration audit outcomes require terminal-phase operation detail")
    if outcome.status != AuditStatus.UNVERIFIED and outcome.unverified_result is not None:
        raise ValueError("Only unverified integration outcomes may retain result data")


def integration_exception_evidence(
    exc: BaseException,
    pending_detail: object,
    *,
    durable: bool,
    pending_event_id: UUID | None,
) -> tuple[Literal[AuditStatus.UNVERIFIED, AuditStatus.FAILURE], IntegrationOperationDetail | None]:
    """Preserves failure disposition and chooses the available audit evidence."""
    if isinstance(exc, asyncio.CancelledError):
        disposition = getattr(
            exc, "failure_disposition", IntegrationFailureDisposition.NOT_DISPATCHED
        )
        if durable:
            exc.failure_disposition = disposition
    else:
        disposition = getattr(exc, "failure_disposition", None)
        if durable and disposition is None:
            disposition = (
                IntegrationFailureDisposition.AMBIGUOUS
                if pending_event_id is not None
                else IntegrationFailureDisposition.NOT_DISPATCHED
            )
            exc.failure_disposition = disposition
    detail = _exception_operation_detail(exc, pending_detail)
    status = (
        AuditStatus.UNVERIFIED
        if disposition is IntegrationFailureDisposition.AMBIGUOUS
        and isinstance(detail, TerminalIntegrationOperationDetail)
        else AuditStatus.FAILURE
    )
    return status, detail


def _exception_operation_detail(
    exc: BaseException,
    pending_detail: object,
) -> IntegrationOperationDetail | None:
    detail = getattr(exc, "operation_detail", None)
    if isinstance(detail, TerminalIntegrationOperationDetail):
        return detail
    if isinstance(pending_detail, PendingIntegrationOperationDetail):
        return pending_detail
    return None
