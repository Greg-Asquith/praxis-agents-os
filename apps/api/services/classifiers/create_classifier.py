# apps/api/services/classifiers/create_classifier.py

"""Create a workspace classifier."""

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.classifiers import Classifier
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.classifiers.schemas import ClassifierCreateRequest, ClassifierRead
from services.classifiers.utils import (
    MAX_CLASSIFIERS_PER_WORKSPACE,
    classify_classifier_integrity_error,
    require_classifier_write_access,
)


async def create_classifier(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: ClassifierCreateRequest,
) -> ClassifierRead:
    require_classifier_write_access(membership)
    await db.execute(select(Workspace.id).where(Workspace.id == workspace.id).with_for_update())
    count = await db.scalar(
        select(func.count())
        .select_from(Classifier)
        .where(
            Classifier.workspace_id == workspace.id,
            Classifier.deleted.is_(False),
        )
    )
    if (count or 0) >= MAX_CLASSIFIERS_PER_WORKSPACE:
        raise ConflictError(
            f"A workspace can have at most {MAX_CLASSIFIERS_PER_WORKSPACE} classifiers",
            conflicting_resource="classifier",
        )

    classifier = Classifier(
        workspace_id=workspace.id,
        created_by=actor.id,
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        instructions=payload.instructions,
        labels=[label.model_dump() for label in payload.labels],
        model_provider=payload.model_provider,
        model=payload.model,
        is_active=payload.is_active,
    )
    try:
        async with db.begin_nested():
            db.add(classifier)
            await db.flush([classifier])
    except IntegrityError as exc:
        if classifier in db:
            db.expunge(classifier)
        conflict = classify_classifier_integrity_error(exc)
        if conflict is not None:
            raise conflict from exc
        raise

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.CLASSIFIER,
        resource_id=classifier.id,
        actor=actor,
        details={"classifier_name": classifier.name},
    )
    await db.refresh(classifier)
    return ClassifierRead.from_classifier(classifier)
