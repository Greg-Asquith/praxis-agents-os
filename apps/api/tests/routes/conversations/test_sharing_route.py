"""Cookie authentication and input validation for conversation sharing."""

import pytest

from tests.security.test_conversation_sharing import sharing_case
from utils.security import generate_csrf_token

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("visibility", ["workspace", "private"])
async def test_sharing_requires_csrf_for_cookie_auth(db_session, db_async_client, visibility):
    case = await sharing_case(db_session)
    csrf = generate_csrf_token(case.owner_token)
    db_async_client.cookies.set("session", case.owner_token)
    db_async_client.cookies.set("csrf", csrf)
    path = f"/api/v1/conversations/{case.conversation.id}/sharing"
    denied = await db_async_client.put(path, json={"visibility": visibility})
    assert denied.status_code == 403
    accepted = await db_async_client.put(
        path,
        json={"visibility": visibility},
        headers={"x-csrf-token": csrf, "origin": "http://localhost:3000"},
    )
    assert accepted.status_code == 200, accepted.text


@pytest.mark.parametrize("payload", [{}, {"visibility": "public"}, {"visibility": None}])
async def test_sharing_rejects_invalid_visibility(db_session, db_async_client, payload):
    case = await sharing_case(db_session)
    response = await db_async_client.put(
        f"/api/v1/conversations/{case.conversation.id}/sharing",
        json=payload,
        headers=case.owner_headers,
    )
    assert response.status_code == 422
