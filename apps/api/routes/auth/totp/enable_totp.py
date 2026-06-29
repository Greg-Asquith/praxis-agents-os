# apps/api/routes/auth/enable_totp.py

"""Route for enabling TOTP."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import enable_totp as enable_totp_service
from services.auth.schemas import TotpEnableRequest, TotpEnableResponse

router = APIRouter()


@router.post("/totp/enable")
async def enable_totp(
    request: Request,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
    payload: TotpEnableRequest,
) -> TotpEnableResponse:
    return await enable_totp_service(db, request=request, user=user, payload=payload)
