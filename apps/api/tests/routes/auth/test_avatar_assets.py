# apps/api/tests/routes/auth/test_avatar_assets.py

"""Route tests for current-user avatar assets."""

from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.settings import settings
from tests.factories import build_user
from tests.support.auth import bearer_headers
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


def _relative_url(absolute_url: str) -> str:
    parsed = urlsplit(absolute_url)
    return f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path


async def _auth_headers(db_session: AsyncSession) -> dict[str, str]:
    user = build_user(email="avatar-route@example.com")
    db_session.add(user)
    await db_session.flush()
    session = await session_manager.create_session(db_session, str(user.id))
    await db_session.commit()
    return bearer_headers(session["session_token"])


async def test_avatar_upload_confirm_and_delete_routes(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    headers = await _auth_headers(db_session)

    upload_response = await db_async_client.post(
        "/api/v1/auth/me/avatar/upload",
        headers=headers,
        json={
            "filename": "avatar.png",
            "content_type": "image/png",
            "size_bytes": 7,
        },
    )
    assert upload_response.status_code == 200
    upload_grant = upload_response.json()

    put_response = await db_async_client.put(
        _relative_url(upload_grant["upload"]["url"]),
        content=b"new-png",
        headers=upload_grant["upload"]["headers"],
    )
    assert put_response.status_code == 204

    confirm_response = await db_async_client.post(
        "/api/v1/auth/me/avatar/confirm",
        headers=headers,
        json={"upload_token": upload_grant["upload_token"]},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["avatar_url"].endswith(upload_grant["upload"]["ref"]["key"])

    delete_response = await db_async_client.delete("/api/v1/auth/me/avatar", headers=headers)
    assert delete_response.status_code == 200
    assert delete_response.json()["avatar_url"] is None
