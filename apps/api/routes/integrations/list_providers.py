# apps/api/routes/integrations/list_providers.py

"""List enabled integration provider manifests."""

from fastapi import APIRouter, Depends

from core.dependencies import require_read
from services.integrations.connections.schemas import ProviderRead
from services.integrations.providers_view import list_providers as list_providers_service

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/providers")
async def list_providers() -> list[ProviderRead]:
    return list_providers_service()
