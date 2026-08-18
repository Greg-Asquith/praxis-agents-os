# apps/api/services/classifiers/list_classifiers.py

"""List classifiers in one workspace."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.classifiers import Classifier
from models.workspace import Workspace
from services.classifiers.schemas import ClassifierRead, ClassifiersListResponse
from utils.pagination import paginate


async def list_classifiers(
    db: AsyncSession,
    *,
    workspace: Workspace,
    limit: int,
    offset: int,
    include_inactive: bool,
) -> ClassifiersListResponse:
    filters = [
        Classifier.workspace_id == workspace.id,
        Classifier.deleted.is_(False),
    ]
    if not include_inactive:
        filters.append(Classifier.is_active.is_(True))
    classifiers, total = await paginate(
        db,
        select(Classifier).where(*filters),
        Classifier.updated_at.desc(),
        limit=limit,
        offset=offset,
    )
    return ClassifiersListResponse(
        classifiers=[ClassifierRead.from_classifier(item) for item in classifiers],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
