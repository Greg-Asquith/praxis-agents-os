# apps/api/routes/health/readiness.py

"""Database-backed service readiness."""

from fastapi import APIRouter

from core.database import check_database_connection
from core.exceptions.database import DatabaseError
from core.exceptions.general import ProblemDetailsError
from routes.health.domain import ReadinessResponse

router = APIRouter()


@router.get("/readyz", include_in_schema=False)
async def get_readiness() -> ReadinessResponse:
    try:
        await check_database_connection()
    except DatabaseError as exc:
        raise ProblemDetailsError(
            "Database is not ready",
            status_code=503,
            title="Service Not Ready",
        ) from exc
    return ReadinessResponse()
