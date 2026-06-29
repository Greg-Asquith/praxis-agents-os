# apps/api/routes/auth/list_oauth_providers.py

"""Route for listing OAuth providers."""

from fastapi import APIRouter

from services.auth import list_oauth_providers as list_oauth_providers_service
from services.auth.schemas import AuthProvidersResponse

router = APIRouter()


@router.get("/oauth/providers")
async def list_oauth_providers() -> AuthProvidersResponse:
    return list_oauth_providers_service()
