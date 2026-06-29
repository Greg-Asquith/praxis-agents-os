# apps/api/routes/auth/create_oauth_authorization_url.py

"""Route for creating OAuth authorization URLs."""

from typing import Annotated

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep
from services.auth import create_oauth_authorization_url
from services.auth.schemas import OAuthAuthorizationUrlRequest, OAuthAuthorizationUrlResponse

router = APIRouter()


@router.post("/oauth/{provider_name}/authorization-url")
async def create_oauth_authorization_url_route(
    request: Request,
    db: AsyncDbSessionDep,
    provider_name: Annotated[str, Path(min_length=1, max_length=50)],
    payload: OAuthAuthorizationUrlRequest,
) -> OAuthAuthorizationUrlResponse:
    return await create_oauth_authorization_url(
        db,
        request=request,
        provider_name=provider_name,
        payload=payload,
    )
