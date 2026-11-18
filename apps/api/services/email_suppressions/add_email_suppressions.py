# apps/api/services/email_suppressions/add_email_suppressions.py

"""Add pasted addresses to the workspace Do Not Email list with one reason."""

from fastapi import Request
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.email_suppression import WorkspaceEmailSuppression
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.email_suppressions.schemas import (
    EmailSuppressionAddRequest,
    EmailSuppressionAddResponse,
)
from services.email_suppressions.utils import (
    address_match_key,
    parse_listed_address,
    suppression_read,
)


async def add_email_suppressions(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    payload: EmailSuppressionAddRequest,
) -> EmailSuppressionAddResponse:
    # Keyed by match key in paste order, so variants of one address in a paste count once.
    addresses: dict[str, str] = {}
    invalid: list[str] = []
    for value in payload.addresses:
        address = parse_listed_address(value)
        if address is None:
            invalid.append(value.strip())
        else:
            addresses.setdefault(address_match_key(address), address)

    added: list[WorkspaceEmailSuppression] = []
    if addresses:
        # A concurrent add of the same address reports it as already listed, not as an error.
        result = await db.execute(
            insert(WorkspaceEmailSuppression)
            .values(
                [
                    {
                        "workspace_id": workspace.id,
                        "email": address,
                        "match_key": key,
                        "reason": payload.reason,
                        "created_by_user_id": actor.id,
                    }
                    for key, address in addresses.items()
                ]
            )
            .on_conflict_do_nothing(constraint="uq_workspace_email_suppressions_match_key")
            .returning(WorkspaceEmailSuppression)
        )
        position = {key: index for index, key in enumerate(addresses)}
        added = sorted(result.scalars().all(), key=lambda entry: position[entry.match_key])

    for entry in added:
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.CREATE,
            resource_type=AuditResourceType.EMAIL_SUPPRESSION,
            resource_id=entry.id,
            actor=actor,
            details={"email": entry.email, "reason": entry.reason},
        )

    added_keys = {entry.match_key for entry in added}
    return EmailSuppressionAddResponse(
        added=[suppression_read(entry, actor) for entry in added],
        already_listed=[address for key, address in addresses.items() if key not in added_keys],
        invalid=invalid,
    )
