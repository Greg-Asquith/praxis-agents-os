# apps/api/routes/auth/oauth/unlink_oauth_provider.py

"""Route for unlinking an OAuth provider from the current user."""

from typing import Annotated

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import unlink_oauth_provider
from services.auth.schemas import IdentitiesResponse

router = APIRouter()


@router.delete("/oauth/{provider_name}/link")
async def unlink_oauth_provider_route(
    request: Request,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
    provider_name: Annotated[str, Path(min_length=1, max_length=50)],
) -> IdentitiesResponse:
    return await unlink_oauth_provider(
        db,
        request=request,
        user=user,
        provider_name=provider_name,
    )
