# apps/api/services/classifiers/utils.py

"""Shared classifier service helpers."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError, NotFoundError
from models.classifiers import Classifier
from models.workspace import Workspace, WorkspaceMembership
from services.workspaces.utils import MANAGER_ROLES

CLASSIFIER_NAME_UNIQUE_CONSTRAINT = "uq_classifiers_workspace_name"
MAX_CLASSIFIERS_PER_WORKSPACE = 50


async def get_classifier_for_workspace(
    db: AsyncSession, *, workspace: Workspace, classifier_id: UUID
) -> Classifier:
    classifier = await db.scalar(
        select(Classifier).where(
            Classifier.id == classifier_id,
            Classifier.workspace_id == workspace.id,
            Classifier.deleted.is_(False),
        )
    )
    if classifier is None:
        raise NotFoundError(
            "Classifier not found",
            resource_type="classifier",
            resource_id=str(classifier_id),
        )
    return classifier


def require_classifier_write_access(membership: WorkspaceMembership) -> None:
    if membership.role not in MANAGER_ROLES:
        raise AuthorizationError(
            "Requires workspace owner or admin access",
            details={
                "allowed_roles": sorted(MANAGER_ROLES),
                "membership_id": str(membership.id),
                "membership_role": membership.role,
                "workspace_id": str(membership.workspace_id),
                "user_id": str(membership.user_id),
            },
        )


def classify_classifier_integrity_error(exc: IntegrityError) -> ConflictError | None:
    if CLASSIFIER_NAME_UNIQUE_CONSTRAINT in str(exc):
        return ConflictError(
            "A classifier with this name already exists in the workspace",
            conflicting_resource="classifier",
        )
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    if getattr(diag, "constraint_name", None) == CLASSIFIER_NAME_UNIQUE_CONSTRAINT:
        return ConflictError(
            "A classifier with this name already exists in the workspace",
            conflicting_resource="classifier",
        )
    return None
