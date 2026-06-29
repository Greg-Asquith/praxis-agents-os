# apps/api/routes/auth/setup_totp.py

"""Route for setting up TOTP."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import setup_totp as setup_totp_service
from services.auth.schemas import TotpSetupResponse

router = APIRouter()


@router.post("/totp/setup")
async def setup_totp(
    request: Request,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
) -> TotpSetupResponse:
    return await setup_totp_service(db, request=request, user=user)
