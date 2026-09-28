"""HTTP-boundary tests for authenticated metadata routes."""

from httpx2 import AsyncClient


async def test_openapi_schema_route_requires_authentication(
    db_async_client: AsyncClient,
) -> None:
    response = await db_async_client.get("/api/v1/meta/openapi.json")

    assert response.status_code == 401


async def test_anonymous_fastapi_documentation_routes_remain_disabled(
    db_async_client: AsyncClient,
) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = await db_async_client.get(path)
        assert response.status_code == 404
