"""Notion Knowledge Base source adapter contracts."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationRateLimitError,
    IntegrationValidationError,
)
from integrations.notion import knowledge_source as source_module
from integrations.notion.client import NotionClient
from integrations.notion.knowledge_source import (
    fetch_source,
    notion_client_for_connection,
    parse_source,
    preview_source,
)
from services.integrations.plugin import (
    KnowledgeSourceAccessLostError,
)

PAGE_ID = "01234567-89ab-cdef-0123-456789abcdef"
PAGE_ID_COMPACT = PAGE_ID.replace("-", "")
PAGE_URL = f"https://www.notion.so/Launch-plan-{PAGE_ID_COMPACT}"
FIXTURES = Path(__file__).parent / "fixtures"


async def _token(_force: bool) -> str:
    return "notion-token"


def _resource() -> SimpleNamespace:
    return SimpleNamespace(external_id="workspace-1", display_name="Example workspace")


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _page_payload(*, title: str = "Launch plan", page_id: str = PAGE_ID) -> dict[str, Any]:
    payload = _fixture("knowledge_page.json")
    payload["id"] = page_id
    payload["properties"]["Name"]["title"][0]["plain_text"] = title
    return payload


@pytest.mark.parametrize(
    "url",
    [
        PAGE_URL,
        f"https://notion.so/{PAGE_ID_COMPACT}",
    ],
)
def test_parse_source_accepts_supported_notion_page_urls(url: str) -> None:
    assert parse_source(url) == {"page_id": PAGE_ID}


@pytest.mark.parametrize(
    "url",
    [
        f"http://www.notion.so/{PAGE_ID_COMPACT}",
        f"https://notion.site/{PAGE_ID_COMPACT}",
        f"https://notion.so.example.com/{PAGE_ID_COMPACT}",
    ],
)
def test_parse_source_rejects_unsupported_or_invalid_urls(url: str) -> None:
    with pytest.raises(IntegrationValidationError, match="valid Notion page URL"):
        parse_source(url)


@pytest.mark.parametrize(
    "status_code",
    [
        403,
    ],
)
async def test_preview_maps_definitive_access_loss(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code, json={}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:

        def client_for_connection(*_args) -> NotionClient:
            return NotionClient(_token, client=http_client)

        monkeypatch.setattr(source_module, "notion_client_for_connection", client_for_connection)
        with pytest.raises(KnowledgeSourceAccessLostError):
            await preview_source(None, None, _resource(), parse_source(PAGE_URL))


async def test_preview_keeps_rate_limits_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_delay(_seconds: float) -> None:
        return None

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, json={}, request=request)

    monkeypatch.setattr("services.integrations.http.asyncio.sleep", no_delay)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:

        def client_for_connection(*_args) -> NotionClient:
            return NotionClient(_token, client=http_client)

        monkeypatch.setattr(source_module, "notion_client_for_connection", client_for_connection)
        with pytest.raises(IntegrationRateLimitError):
            await preview_source(None, None, _resource(), parse_source(PAGE_URL))


async def test_fetch_rejects_incomplete_provider_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        payload = _fixture("knowledge_page_markdown.json")
        payload["truncated"] = True
        if not request.url.path.endswith("/markdown"):
            payload = _page_payload()
        return httpx2.Response(200, json=payload, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:

        def client_for_connection(*_args) -> NotionClient:
            return NotionClient(_token, client=http_client)

        monkeypatch.setattr(source_module, "notion_client_for_connection", client_for_connection)
        with pytest.raises(IntegrationValidationError, match="incomplete page Markdown"):
            await fetch_source(None, None, _resource(), PAGE_ID)


def test_connection_client_rejects_unusable_connection_before_token_resolution() -> None:
    class Database:
        pass

    connection = SimpleNamespace(
        id=uuid4(),
        credential_id=uuid4(),
        provider_key="notion",
        deleted=False,
        owner_user_id=uuid4(),
        owner_workspace_id=None,
        status="revoked",
    )

    with pytest.raises(IntegrationAuthError, match="credentials are not available"):
        notion_client_for_connection(Database(), connection)


async def test_connection_client_uses_isolated_refresh_and_connection_pacing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential_id = uuid4()
    connection_id = uuid4()
    owner_user_id = uuid4()
    credential = SimpleNamespace(
        id=credential_id,
        provider_key="notion",
        owner_user_id=owner_user_id,
        owner_workspace_id=None,
        access_token="fresh-token",  # noqa: S106 - inert test token
    )

    class Database:
        def in_transaction(self) -> bool:
            return False

        async def commit(self) -> None:
            raise AssertionError("provider adapters must not commit caller transactions")

    database = Database()
    connection = SimpleNamespace(
        id=connection_id,
        credential_id=credential_id,
        provider_key="notion",
        deleted=False,
        owner_user_id=owner_user_id,
        owner_workspace_id=None,
        status="active",
    )
    calls: list[tuple[UUID, bool, str, tuple[UUID, None]]] = []

    async def fresh_credential(
        _db,
        *,
        credential_id,
        refresh_token,
        force,
        expected_provider_key,
        expected_owner,
    ):
        assert refresh_token is not None
        calls.append((credential_id, force, expected_provider_key, expected_owner))
        return credential

    from services.integrations.credentials import (
        build_personal_oauth_access_token_resolver as resolver,
    )

    resolver_module = __import__(resolver.__module__, fromlist=["ensure_fresh_credential"])
    monkeypatch.setattr(resolver_module, "ensure_fresh_credential", fresh_credential)

    client = notion_client_for_connection(database, connection)

    assert client._pacing_key == str(connection_id)
    assert await client._access_token(False) == "fresh-token"
    assert calls == [(credential_id, False, "notion", (owner_user_id, None))]


async def test_connection_client_rejects_mismatched_credential_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = SimpleNamespace(
        id=uuid4(),
        credential_id=uuid4(),
        provider_key="notion",
        deleted=False,
        owner_user_id=uuid4(),
        owner_workspace_id=None,
        status="active",
    )

    async def fresh_credential(*_args, **_kwargs):
        return SimpleNamespace(
            provider_key="notion",
            owner_user_id=None,
            owner_workspace_id=uuid4(),
            access_token="fresh-token",  # noqa: S106 - inert test token
        )

    from services.integrations.credentials import (
        build_personal_oauth_access_token_resolver as resolver,
    )

    resolver_module = __import__(resolver.__module__, fromlist=["ensure_fresh_credential"])
    monkeypatch.setattr(resolver_module, "ensure_fresh_credential", fresh_credential)

    client = notion_client_for_connection(
        SimpleNamespace(in_transaction=lambda: False),
        connection,
    )
    with pytest.raises(IntegrationAuthError, match="credentials are not available"):
        await client._access_token(False)


def test_connection_client_rejects_an_open_caller_transaction() -> None:
    connection = SimpleNamespace(
        id=uuid4(),
        credential_id=uuid4(),
        provider_key="notion",
        deleted=False,
        owner_user_id=uuid4(),
        owner_workspace_id=None,
        status="active",
    )

    class Database:
        def in_transaction(self) -> bool:
            return True

        async def commit(self) -> None:
            raise AssertionError("provider adapters must not commit caller transactions")

    with pytest.raises(RuntimeError, match="must close database transactions"):
        notion_client_for_connection(Database(), connection)
