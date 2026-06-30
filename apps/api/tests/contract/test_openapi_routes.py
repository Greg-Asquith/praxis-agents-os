# apps/api/tests/contract/test_openapi_routes.py
"""Auth, user, and workspace route contract tests."""


def test_auth_and_user_routes_are_registered_under_api_v1(
    openapi_schema: dict[str, object],
) -> None:
    paths = set(openapi_schema["paths"])

    assert {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/auth/oauth/providers",
        "/api/v1/auth/oauth/{provider_name}/authorization-url",
        "/api/v1/auth/oauth/{provider_name}/callback",
        "/api/v1/auth/sessions",
        "/api/v1/auth/totp/verify",
        "/api/v1/users/",
        "/api/v1/users/{user_id}",
        "/api/v1/users/{user_id}/password",
    } <= paths


def test_workspace_routes_are_registered_under_api_v1(
    openapi_schema: dict[str, object],
) -> None:
    paths = set(openapi_schema["paths"])

    assert {
        "/api/v1/workspaces/",
        "/api/v1/workspaces/{workspace_id}",
        "/api/v1/workspaces/{workspace_id}/memberships",
        "/api/v1/workspaces/{workspace_id}/memberships/{membership_id}",
        "/api/v1/workspaces/{workspace_id}/invitations",
        "/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}",
        "/api/v1/workspaces/invitations/accept",
        "/api/v1/workspaces/invitations/{invitation_id}/accept",
    } <= paths


def test_model_catalog_route_is_registered_under_api_v1(
    openapi_schema: dict[str, object],
) -> None:
    paths = set(openapi_schema["paths"])

    assert "/api/v1/models/catalog" in paths


def test_conversation_routes_are_registered_under_api_v1(
    openapi_schema: dict[str, object],
) -> None:
    paths = set(openapi_schema["paths"])

    assert {
        "/api/v1/conversations/",
        "/api/v1/conversations/{conversation_id}",
        "/api/v1/conversations/{conversation_id}/turns",
        "/api/v1/conversations/{conversation_id}/messages",
        "/api/v1/conversations/{conversation_id}/active-run",
    } <= paths


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
