# apps/api/services/jobs/handlers/rotate_credential_encryption.py

"""Manual credential-key rotation sweep.

Enqueue with ``enqueue_job(..., kind='integrations.rotate_credential_encryption')``
after deploying a root-key list whose newest entry is the new key.
"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import ExternalCredential
from models.jobs import Job
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.utils import (
    credential_encryption_key_id,
    ensure_credential_keys_loaded,
    record_integration_audit,
)
from services.jobs.registry import job_handler

ROTATE_CREDENTIAL_ENCRYPTION_KIND = "integrations.rotate_credential_encryption"
_ROTATION_BATCH_SIZE = 100


@job_handler(kind=ROTATE_CREDENTIAL_ENCRYPTION_KIND, timeout=300.0, max_attempts=3)
async def rotate_credential_encryption(db: AsyncSession, job: Job) -> None:
    await ensure_credential_keys_loaded(db)
    current_key_id = credential_encryption_key_id()
    rotated = 0
    while True:
        ids = list(
            (
                await db.scalars(
                    select(ExternalCredential.id)
                    .where(
                        ExternalCredential.deleted.is_(False),
                        ExternalCredential.revoked_at.is_(None),
                        or_(
                            ExternalCredential.access_token_encrypted.is_not(None),
                            ExternalCredential.refresh_token_encrypted.is_not(None),
                        ),
                        or_(
                            ExternalCredential.encryption_key_id.is_(None),
                            ExternalCredential.encryption_key_id != current_key_id,
                        ),
                    )
                    .order_by(ExternalCredential.id)
                    .limit(_ROTATION_BATCH_SIZE)
                )
            ).all()
        )
        if not ids:
            break

        for credential_id in ids:
            credential = await db.scalar(
                select(ExternalCredential)
                .where(ExternalCredential.id == credential_id)
                .with_for_update()
            )
            if (
                credential is None
                or credential.deleted
                or credential.revoked_at is not None
                or (
                    credential.access_token_encrypted is None
                    and credential.refresh_token_encrypted is None
                )
                or credential.encryption_key_id == current_key_id
            ):
                continue
            access_token = credential.access_token
            refresh_token = credential.refresh_token
            credential.access_token = access_token
            credential.refresh_token = refresh_token
            credential.encryption_key_id = current_key_id
            rotated += 1
        await db.commit()

    await record_integration_audit(
        db,
        workspace_id=job.workspace_id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INTEGRATION_CREDENTIAL,
        resource_id=None,
        details={"rotated_count": rotated, "encryption_key_id": current_key_id},
    )
