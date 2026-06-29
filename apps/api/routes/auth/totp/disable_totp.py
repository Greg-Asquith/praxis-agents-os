# apps/api/routes/auth/disable_totp.py

"""Route for disabling TOTP."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import disable_totp as disable_totp_service
from services.auth.schemas import MessageResponse, TotpDisableRequest

router = APIRouter()


@router.delete("/totp")
async def disable_totp(
    request: Request,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
    payload: TotpDisableRequest,
) -> MessageResponse:
    return await disable_totp_service(db, request=request, user=user, payload=payload)
