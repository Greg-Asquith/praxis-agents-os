"""Integration-route fixtures with suite-local provider registration."""

from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.settings import settings
from integrations.gmail.settings import gmail_settings
from integrations.google_ads.settings import google_ads_settings
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.integrations.manifest import PROVIDER_MANIFESTS, register_provider_manifest
from services.integrations.plugin import PROVIDER_PLUGINS, register_provider_plugin
from services.secrets import factory as secrets_factory
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers


@pytest.fixture(autouse=True)
def integration_route_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from integrations.airtable import PROVIDER as AIRTABLE_PROVIDER
    from integrations.gmail import PROVIDER as GMAIL_PROVIDER
    from integrations.google_ads import PROVIDER as GOOGLE_ADS_PROVIDER

    original = dict(PROVIDER_MANIFESTS)
    original_plugins = dict(PROVIDER_PLUGINS)
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()
    for plugin in (GMAIL_PROVIDER, GOOGLE_ADS_PROVIDER, AIRTABLE_PROVIDER):
        register_provider_plugin(plugin)
        register_provider_manifest(plugin.manifest)
    monkeypatch.setattr(gmail_settings, "GMAIL_OAUTH_CLIENT_ID", "gmail-integration-client")
    monkeypatch.setattr(
        gmail_settings,
        "GMAIL_OAUTH_CLIENT_SECRET",
        type(gmail_settings.GMAIL_OAUTH_CLIENT_SECRET)("gmail-integration-secret"),
    )
    monkeypatch.setattr(
        google_ads_settings,
        "GOOGLE_ADS_OAUTH_CLIENT_ID",
        "google-ads-integration-client",
    )
    monkeypatch.setattr(
        google_ads_settings,
        "GOOGLE_ADS_OAUTH_CLIENT_SECRET",
        type(google_ads_settings.GOOGLE_ADS_OAUTH_CLIENT_SECRET)("google-ads-integration-secret"),
    )
    monkeypatch.setattr(
        settings,
        "INTEGRATIONS_OAUTH_REDIRECT_URI",
        "http://frontend.test/integrations/oauth/callback",
    )
    monkeypatch.setattr(settings, "CREDENTIAL_MASTER_KEYS", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    secrets_factory._provider = None
    secrets_factory._provider_key = None
    yield
    PROVIDER_MANIFESTS.clear()
    PROVIDER_MANIFESTS.update(original)
    PROVIDER_PLUGINS.clear()
    PROVIDER_PLUGINS.update(original_plugins)
    secrets_factory._provider = None
    secrets_factory._provider_key = None


@pytest_asyncio.fixture
async def integration_identity(db_session: AsyncSession) -> AsyncIterator[dict[str, object]]:
    user = build_user(email=f"integration-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"integration-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    db_session.add_all([user, workspace, membership])
    await db_session.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db_session, str(user.id))
    await db_session.commit()
    yield {
        "user": user,
        "workspace": workspace,
        "membership": membership,
        "headers": bearer_headers(session["session_token"]),
        "session_token": session["session_token"],
    }


async def create_identity(
    db: AsyncSession,
    *,
    role: WorkspaceRole,
    workspace: Workspace | None = None,
) -> tuple[User, Workspace, WorkspaceMembership, dict[str, str]]:
    user = build_user(email=f"integration-{uuid4().hex}@example.com")
    target = workspace or build_workspace(slug=f"integration-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=target.id,
        user_id=user.id,
        role=role,
    )
    db.add_all([user, target, membership])
    await db.flush()
    user.default_workspace_id = target.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return user, target, membership, bearer_headers(session["session_token"])
