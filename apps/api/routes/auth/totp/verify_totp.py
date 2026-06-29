# apps/api/routes/auth/verify_totp.py

"""Route for verifying TOTP."""

from fastapi import APIRouter, Request, Response

from core.dependencies import AsyncDbSessionDep
from services.auth import verify_totp as verify_totp_service
from services.auth.schemas import AuthResponse, TotpVerifyRequest

router = APIRouter()


@router.post("/totp/verify")
async def verify_totp(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    payload: TotpVerifyRequest,
) -> AuthResponse:
    return await verify_totp_service(db, request=request, response=response, payload=payload)
