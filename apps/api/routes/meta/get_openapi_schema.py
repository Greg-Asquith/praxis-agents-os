# apps/api/routes/meta/get_openapi_schema.py

"""Authenticated OpenAPI schema route."""

from typing import Any

from fastapi import APIRouter, Request, Response

from core.dependencies import CurrentUserDep

router = APIRouter()


@router.get("/openapi.json")
async def get_openapi_schema(
    _actor: CurrentUserDep,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return request.app.openapi()
