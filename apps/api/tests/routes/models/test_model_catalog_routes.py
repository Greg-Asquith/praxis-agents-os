"""HTTP-boundary tests for the authenticated model catalog route."""

import importlib
from uuid import uuid4

from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.settings import settings
from services.agents.models.domain import ModelInfo
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers


async def _authenticated_headers(db: AsyncSession) -> dict[str, str]:
    user = build_user(email=f"model-catalog-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"model-catalog-{uuid4().hex[:8]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    db.add_all([user, workspace, membership])
    await db.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return bearer_headers(session["session_token"])


async def test_model_catalog_route_serializes_transport_and_filters_blank_vertex_ids(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch,
) -> None:
    headers = await _authenticated_headers(db_session)
    catalog_module = importlib.import_module("services.agents.models.list_model_catalog")
    visible = ModelInfo(
        provider="google",
        model="gemini-visible",
        display_name="Gemini Visible",
        context_window=128_000,
        model_type="standard",
        vertex_model="gemini-visible",
    )
    hidden = ModelInfo(
        provider="google",
        model="gemini-hidden",
        display_name="Gemini Hidden",
        context_window=128_000,
        model_type="standard",
        vertex_model="   ",
    )
    monkeypatch.setattr(catalog_module, "list_models", lambda: [visible, hidden])
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODELS_ENABLED", False)

    response = await db_async_client.get("/api/v1/models/catalog", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    providers = {provider["provider"]: provider for provider in payload["providers"]}
    assert providers["google"]["transport"] == "google-cloud"
    assert [model["id"] for model in payload["models"]] == ["google:gemini-visible"]
