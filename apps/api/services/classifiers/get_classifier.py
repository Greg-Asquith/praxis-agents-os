# apps/api/services/classifiers/get_classifier.py

"""Read a workspace classifier."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from services.classifiers.schemas import ClassifierRead
from services.classifiers.utils import get_classifier_for_workspace


async def get_classifier(
    db: AsyncSession, *, workspace: Workspace, classifier_id: UUID
) -> ClassifierRead:
    classifier = await get_classifier_for_workspace(
        db, workspace=workspace, classifier_id=classifier_id
    )
    return ClassifierRead.from_classifier(classifier)
