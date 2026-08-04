# apps/api/services/jobs/handlers/converge_application_encryption.py

"""Manual application-encryption convergence and removal-proof scan."""

import logging
from dataclasses import asdict, dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import CustomValueError
from models.jobs import Job
from models.user import User, UserAuth
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_operation_audit_event,
)
from services.jobs.registry import job_handler
from services.security import ensure_application_encryption_keys_loaded
from utils.security import decrypt_data, encrypt_data, is_encrypted_with_primary

APPLICATION_ENCRYPTION_JOB_KIND = "security.converge_application_encryption"
_BATCH_SIZE = 100
_MODE_CONVERGE = "converge"
_MODE_CHECK = "check"

logger = logging.getLogger(__name__)


@dataclass
class EncryptionScanReport:
    total: int = 0
    primary: int = 0
    stale: int = 0
    undecryptable: int = 0
    rotated: int = 0


@job_handler(kind=APPLICATION_ENCRYPTION_JOB_KIND, timeout=300.0, max_attempts=1)
async def converge_application_encryption(db: AsyncSession, job: Job) -> None:
    """Scan or converge every durable application-encrypted database value."""
    await ensure_application_encryption_keys_loaded(db)
    mode = _parse_mode(job.payload)
    report = EncryptionScanReport()

    await _scan_table(
        db,
        model=User,
        encrypted_fields=("totp_secret_encrypted", "backup_codes_encrypted"),
        mode=mode,
        report=report,
    )
    await _scan_table(
        db,
        model=UserAuth,
        encrypted_fields=("access_token_encrypted", "refresh_token_encrypted"),
        mode=mode,
        report=report,
    )

    result = asdict(report)
    job.payload = {
        **job.payload,
        "mode": mode,
        "result": result,
    }
    await safe_record_operation_audit_event(
        db,
        workspace_id=None,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.APPLICATION_ENCRYPTION,
        resource_id=job.id,
        actor_type=AuditActorType.SERVICE,
        actor_display="application-encryption-maintenance",
        status=AuditStatus.SUCCESS,
        details={"job_kind": APPLICATION_ENCRYPTION_JOB_KIND, "mode": mode, **result},
    )


async def _scan_table(
    db: AsyncSession,
    *,
    model: type[User] | type[UserAuth],
    encrypted_fields: tuple[str, ...],
    mode: Literal["converge", "check"],
    report: EncryptionScanReport,
) -> None:
    cursor: UUID | None = None
    columns = tuple(getattr(model, field) for field in encrypted_fields)

    while True:
        statement = select(model).where(or_(*(column.is_not(None) for column in columns)))
        if cursor is not None:
            statement = statement.where(model.id > cursor)
        statement = statement.order_by(model.id).limit(_BATCH_SIZE).with_for_update()
        rows = list((await db.scalars(statement)).all())
        if not rows:
            return

        for row in rows:
            for field in encrypted_fields:
                token = getattr(row, field)
                if token is None:
                    continue
                _inspect_value(
                    row=row,
                    field=field,
                    token=token,
                    mode=mode,
                    report=report,
                )
        cursor = rows[-1].id
        await db.commit()


def _inspect_value(
    *,
    row: User | UserAuth,
    field: str,
    token: str,
    mode: Literal["converge", "check"],
    report: EncryptionScanReport,
) -> None:
    report.total += 1
    if is_encrypted_with_primary(token):
        report.primary += 1
        return

    try:
        plaintext = decrypt_data(token)
    except CustomValueError:
        report.undecryptable += 1
        logger.warning(
            "Application-encrypted value could not be decrypted during rotation scan",
            extra={
                "table": row.__tablename__,
                "row_id": str(row.id),
                "field": field,
            },
        )
        return

    report.stale += 1
    if mode == _MODE_CONVERGE:
        setattr(row, field, encrypt_data(plaintext))
        report.rotated += 1


def _parse_mode(payload: dict[str, object]) -> Literal["converge", "check"]:
    mode = payload.get("mode", _MODE_CONVERGE)
    if mode not in {_MODE_CONVERGE, _MODE_CHECK}:
        raise ValueError("Application encryption job mode must be 'converge' or 'check'")
    return mode
