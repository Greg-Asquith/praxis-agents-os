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
        "/api/v1/auth/me/avatar",
        "/api/v1/auth/me/avatar/confirm",
        "/api/v1/auth/me/avatar/upload",
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
        "/api/v1/workspaces/{workspace_id}/icon",
        "/api/v1/workspaces/{workspace_id}/icon/confirm",
        "/api/v1/workspaces/{workspace_id}/icon/upload",
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


def test_tool_catalog_route_is_registered_under_api_v1(
    openapi_schema: dict[str, object],
) -> None:
    paths = openapi_schema["paths"]

    assert "/api/v1/tools/catalog" in paths
    assert {"get"} == set(paths["/api/v1/tools/catalog"])


def test_agent_routes_are_registered_under_api_v1(
    openapi_schema: dict[str, object],
) -> None:
    paths = set(openapi_schema["paths"])

    assert {
        "/api/v1/agents/",
        "/api/v1/agents/{agent_id}",
    } <= paths
    assert {"get", "post"} <= set(openapi_schema["paths"]["/api/v1/agents/"])
    assert {"get", "patch", "delete"} <= set(openapi_schema["paths"]["/api/v1/agents/{agent_id}"])


def test_audit_event_routes_are_registered_under_api_v1(
    openapi_schema: dict[str, object],
) -> None:
    paths = openapi_schema["paths"]

    assert {
        "/api/v1/audit-events/",
        "/api/v1/audit-events/{event_id}",
        "/api/v1/security-events/",
        "/api/v1/security-events/{event_id}",
    } <= set(paths)
    assert {"get"} == set(paths["/api/v1/audit-events/"])
    assert {"get"} == set(paths["/api/v1/audit-events/{event_id}"])
    assert {"get"} == set(paths["/api/v1/security-events/"])
    assert {"get"} == set(paths["/api/v1/security-events/{event_id}"])


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
        "/api/v1/conversations/{conversation_id}/read",
    } <= paths


def test_agent_run_routes_are_registered_under_api_v1(
    openapi_schema: dict[str, object],
) -> None:
    paths = set(openapi_schema["paths"])

    assert {
        "/api/v1/agent-runs/{run_id}/cancel",
        "/api/v1/agent-runs/{run_id}/approval-state",
        "/api/v1/agent-runs/{run_id}/resume",
    } <= paths


def test_schedule_routes_are_registered_under_api_v1(
    openapi_schema: dict[str, object],
) -> None:
    paths = openapi_schema["paths"]

    assert {
        "/api/v1/schedules/",
        "/api/v1/schedules/preview",
        "/api/v1/schedules/{schedule_id}",
        "/api/v1/schedules/{schedule_id}/pause",
        "/api/v1/schedules/{schedule_id}/enable",
        "/api/v1/schedules/{schedule_id}/run-now",
        "/api/v1/schedules/{schedule_id}/runs",
    } <= set(paths)
    assert {"get", "post"} <= set(paths["/api/v1/schedules/"])
    assert {"post"} == set(paths["/api/v1/schedules/preview"])
    assert {"get", "patch", "delete"} <= set(paths["/api/v1/schedules/{schedule_id}"])
    assert {"post"} == set(paths["/api/v1/schedules/{schedule_id}/pause"])
    assert {"post"} == set(paths["/api/v1/schedules/{schedule_id}/enable"])
    assert {"post"} == set(paths["/api/v1/schedules/{schedule_id}/run-now"])
    assert {"get"} == set(paths["/api/v1/schedules/{schedule_id}/runs"])


def test_storage_provider_routes_are_registered_under_api_v1(
    openapi_schema: dict[str, object],
) -> None:
    paths = set(openapi_schema["paths"])

    assert {
        "/api/v1/storage/public/{object_key}",
        "/api/v1/storage/private/{object_key}",
        "/api/v1/storage/upload/{bucket}/{object_key}",
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
