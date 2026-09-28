# apps/api/tests/contract/test_openapi_routes.py

"""OpenAPI route contract tests."""


def test_operational_metrics_route_is_not_in_openapi_schema(
    openapi_schema: dict[str, object],
) -> None:
    assert "/api/metrics" not in openapi_schema["paths"]


def test_oauth_routes_are_api_posts_not_browser_redirect_gets(
    openapi_schema: dict[str, object],
) -> None:
    paths = openapi_schema["paths"]

    start_route = paths["/api/v1/auth/oauth/{provider_name}/authorization-url"]
    callback_route = paths["/api/v1/auth/oauth/{provider_name}/callback"]

    assert {"post"} == set(start_route)
    assert {"post"} == set(callback_route)


def test_invitation_acceptance_routes_are_api_posts_not_browser_redirect_gets(
    openapi_schema: dict[str, object],
) -> None:
    paths = openapi_schema["paths"]

    assert {"post"} == set(paths["/api/v1/workspaces/invitations/accept"])
    assert {"post"} == set(paths["/api/v1/workspaces/invitations/{invitation_id}/accept"])
