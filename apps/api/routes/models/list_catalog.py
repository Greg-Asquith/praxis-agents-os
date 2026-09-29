# apps/api/routes/models/list_catalog.py

"""Route for listing configured model catalog entries."""

from fastapi import APIRouter

from core.dependencies import CurrentUserDep, CurrentWorkspaceDep
from services.agents.models import list_model_catalog as list_model_catalog_service
from services.agents.models.schemas import ModelCatalogResponse

router = APIRouter()


@router.get("/catalog")
async def list_model_catalog(
    _actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ModelCatalogResponse:
    workspace, _membership = workspace_context
    return list_model_catalog_service(workspace)
