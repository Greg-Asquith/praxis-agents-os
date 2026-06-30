# apps/api/routes/auth/get_identities.py

"""Route for listing the authenticated user's sign-in methods."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import list_user_identities
from services.auth.schemas import IdentitiesResponse

router = APIRouter()


@router.get("/me/identities")
async def get_identities(
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
) -> IdentitiesResponse:
    return await list_user_identities(db, user=user)
