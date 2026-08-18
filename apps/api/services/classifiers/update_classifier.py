# apps/api/services/classifiers/update_classifier.py

"""Update a workspace classifier."""

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.classifiers.schemas import ClassifierRead, ClassifierUpdateRequest
from services.classifiers.utils import (
    classify_classifier_integrity_error,
    get_classifier_for_workspace,
    require_classifier_write_access,
)


async def update_classifier(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    classifier_id: UUID,
    payload: ClassifierUpdateRequest,
) -> ClassifierRead:
    require_classifier_write_access(membership)
    classifier = await get_classifier_for_workspace(
        db, workspace=workspace, classifier_id=classifier_id
    )
    for required in ("name", "display_name", "description", "labels"):
        if required in payload.model_fields_set and getattr(payload, required) is None:
            raise AppValidationError(f"{required} cannot be null", field=required)

    changed_fields: list[str] = []
    for field_name in (
        "name",
        "display_name",
        "description",
        "instructions",
        "labels",
        "model_provider",
        "model",
        "is_active",
    ):
        if field_name not in payload.model_fields_set:
            continue
        value: Any = getattr(payload, field_name)
        if field_name == "labels" and value is not None:
            value = [entry.model_dump() for entry in value]
        if getattr(classifier, field_name) != value:
            setattr(classifier, field_name, value)
            changed_fields.append(field_name)

    if changed_fields:
        try:
            await db.flush()
        except IntegrityError as exc:
            conflict = classify_classifier_integrity_error(exc)
            if conflict is not None:
                raise conflict from exc
            raise
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.CLASSIFIER,
            resource_id=classifier.id,
            actor=actor,
            details={"changed_fields": changed_fields},
        )
        await db.refresh(classifier)
    return ClassifierRead.from_classifier(classifier)
