# apps/api/routes/auth/oauth/complete_oauth_link.py

"""Route for completing an OAuth link for the current user."""

from typing import Annotated

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import complete_oauth_link
from services.auth.schemas import IdentitiesResponse, OAuthCallbackRequest

router = APIRouter()


@router.post("/oauth/{provider_name}/link/callback")
async def complete_oauth_link_route(
    request: Request,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
    provider_name: Annotated[str, Path(min_length=1, max_length=50)],
    payload: OAuthCallbackRequest,
) -> IdentitiesResponse:
    return await complete_oauth_link(
        db,
        request=request,
        user=user,
        provider_name=provider_name,
        payload=payload,
    )
