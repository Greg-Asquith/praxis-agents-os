"""Notion client transport and bounded response normalization."""

import asyncio
import json
from pathlib import Path

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from integrations.notion import pacing
from integrations.notion.client import NOTION_API_VERSION, NotionClient
from integrations.notion.operations.get_data_source import get_data_source
from integrations.notion.operations.get_page import get_page
from integrations.notion.operations.get_page_markdown import (
    MAX_MARKDOWN_BYTES,
    get_page_markdown,
)
from integrations.notion.operations.query_data_source import query_data_source
from integrations.notion.operations.search import search
from integrations.notion.operations.utils import (
    MAX_COMPACT_PROPERTIES_BYTES,
    MAX_MULTI_SELECT_VALUES,
    MAX_NOTION_PROVIDER_CURSOR_CHARS,
    compact_properties,
    pagination_envelope,
    serialized_json_bytes,
)
from services.agents.runtime.untrusted import UntrustedNode, untrusted_content_text
from services.integrations.http import IntegrationRequestPolicy

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


async def token(force: bool) -> str:
    return "fresh-token" if force else "access-token"


async def test_client_sends_headers_post_body_and_cursor() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=fixture("search.json"), request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        result = await search(
            NotionClient(token, client=http_client),
            query="Launch",
            kind="page",
            limit=20,
            start_cursor="cursor-1",
        )

    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/search"
    assert request.headers["Authorization"] == "Bearer access-token"
    assert request.headers["Notion-Version"] == NOTION_API_VERSION
    assert json.loads(request.content) == {
        "filter": {"property": "object", "value": "page"},
        "page_size": 20,
        "query": "Launch",
        "sort": {"timestamp": "last_edited_time", "direction": "descending"},
        "start_cursor": "cursor-1",
    }
    assert result["count"] == 1
    assert result["next_cursor"] == "cursor-2"


async def test_exact_get_url_encodes_provider_ids() -> None:
    seen_path = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_path
        seen_path = request.url.raw_path.decode()
        payload = fixture("page.json")
        payload["id"] = "page/one"
        return httpx2.Response(200, json=payload, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        await get_page(NotionClient(token, client=http_client), page_id="page/one")

    assert seen_path == "/v1/pages/page%2Fone"


async def test_client_honors_retry_after_for_rate_limit(monkeypatch) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx2.Response(429, headers={"Retry-After": "0.25"}, request=request)
        return httpx2.Response(200, json=fixture("page.json"), request=request)

    async def sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("services.integrations.http.asyncio.sleep", sleep)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        await get_page(NotionClient(token, client=http_client), page_id="page-1")

    assert attempts == 2
    assert delays == [0.25]


async def test_client_maps_timeout_after_bounded_retries(monkeypatch) -> None:
    async def sleep(_delay: float) -> None:
        return None

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("provider timeout", request=request)

    monkeypatch.setattr("services.integrations.http.asyncio.sleep", sleep)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        with pytest.raises(IntegrationTimeoutError):
            await get_page(NotionClient(token, client=http_client), page_id="page-1")


async def test_client_preserves_cancellation() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise asyncio.CancelledError

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        with pytest.raises(asyncio.CancelledError):
            await get_page(NotionClient(token, client=http_client), page_id="page-1")


@pytest.mark.parametrize(
    "response",
    [
        lambda request: httpx2.Response(
            200,
            content=b"not-json",
            headers={"Content-Type": "application/json"},
            request=request,
        ),
        lambda request: httpx2.Response(
            200,
            content=b"<html></html>",
            headers={"Content-Type": "text/html"},
            request=request,
        ),
    ],
)
async def test_client_rejects_invalid_or_non_json_responses(response) -> None:
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(response)) as http_client:
        with pytest.raises(IntegrationValidationError):
            await NotionClient(token, client=http_client).get(
                "pages/page-1",
                operation="get_page",
                policy=IntegrationRequestPolicy.READ,
            )


async def test_client_refreshes_once_then_maps_repeated_401() -> None:
    forces: list[bool] = []

    async def access_token(force: bool) -> str:
        forces.append(force)
        return "fresh" if force else "stale"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        with pytest.raises(IntegrationAuthError):
            await get_page(NotionClient(access_token, client=http_client), page_id="page-1")

    assert forces == [False, True]


async def test_process_pacing_waits_after_three_immediate_requests(monkeypatch) -> None:
    clock = 100.0
    delays: list[float] = []

    def now() -> float:
        return clock

    async def sleep(delay: float) -> None:
        nonlocal clock
        delays.append(delay)
        clock += delay + 1e-6

    pacing._reset_for_tests()
    monkeypatch.setattr(pacing, "monotonic", now)
    monkeypatch.setattr(pacing.asyncio, "sleep", sleep)

    for _ in range(4):
        await pacing.acquire("connection-1")

    assert delays == pytest.approx([1 / 3])


async def test_process_pacing_keeps_existing_bucket_state_at_capacity(monkeypatch) -> None:
    clock = 100.0
    delays: list[float] = []

    def now() -> float:
        return clock

    async def sleep(delay: float) -> None:
        nonlocal clock
        delays.append(delay)
        clock += delay + 1e-6

    pacing._reset_for_tests()
    monkeypatch.setattr(pacing, "monotonic", now)
    monkeypatch.setattr(pacing.asyncio, "sleep", sleep)

    for _ in range(3):
        await pacing.acquire("connection-0")
    for index in range(1, 256):
        await pacing.acquire(f"connection-{index}")
    await pacing.acquire("connection-0")

    assert delays == pytest.approx([1 / 3])
    assert len(pacing._buckets) == 256


async def test_page_metadata_and_markdown_are_untrusted_and_bounded() -> None:
    markdown_payload = fixture("page_markdown.json")
    markdown_payload["markdown"] += "🙂" * MAX_MARKDOWN_BYTES

    def handler(request: httpx2.Request) -> httpx2.Response:
        payload = (
            markdown_payload if request.url.path.endswith("/markdown") else fixture("page.json")
        )
        return httpx2.Response(200, json=payload, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = NotionClient(token, client=http_client)
        page = await get_page(client, page_id="page-1")
        markdown = await get_page_markdown(client, page_id="page-1")

    assert isinstance(page["title"], UntrustedNode)
    assert untrusted_content_text(page["title"]) == "Launch plan"
    assert markdown["bytes_returned"] <= MAX_MARKDOWN_BYTES
    assert markdown["truncated"] is True
    assert markdown["provider_truncated"] is True
    assert markdown["unknown_block_count"] == 2
    assert "<unknown" in untrusted_content_text(markdown["markdown"])
    untrusted_content_text(markdown["markdown"]).encode("utf-8").decode("utf-8")


async def test_query_compacts_supported_properties_and_provider_pagination() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        payload = fixture("query.json")
        payload["results"].append(
            {
                "object": "data_source",
                "id": "nested-source-1",
                "title": [{"plain_text": "Nested source"}],
            }
        )
        return httpx2.Response(200, json=payload, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        result = await query_data_source(
            NotionClient(token, client=http_client),
            data_source_id="source-1",
            limit=50,
            start_cursor="cursor-1",
        )

    assert json.loads(requests[0].content) == {
        "page_size": 50,
        "result_type": "page",
        "start_cursor": "cursor-1",
    }
    assert len(result["records"]) == 1
    properties = result["records"][0]["properties"]
    assert untrusted_content_text(properties["Name"]) == "Alpha"
    assert properties["Estimate"] == 8.5
    assert properties["Done"] is True
    assert untrusted_content_text(properties["Priority"]) == "High"
    assert [untrusted_content_text(item) for item in properties["Tags"]] == ["Launch", "P1"]
    assert properties["Formula"] == 1
    assert result["records"][0]["properties_truncated"] is False
    assert result["has_more"] is True
    assert result["next_cursor"] == "cursor-2"
    assert result["incomplete"] is True


def test_compact_properties_caps_aggregate_bytes_and_rich_text_length() -> None:
    properties = {
        f"Property {index}": {
            "type": "rich_text",
            "rich_text": [{"plain_text": "x" * 2_100}],
        }
        for index in range(110)
    }

    compacted = compact_properties(properties, page_id="page-1")

    assert compacted.truncated is True
    assert len(compacted.values) < 100
    assert len(next(iter(compacted.values.values())).content) == 2_000
    assert serialized_json_bytes(compacted.values) <= MAX_COMPACT_PROPERTIES_BYTES


def test_compact_properties_caps_multi_select_values() -> None:
    properties = {
        "Tags": {
            "type": "multi_select",
            "multi_select": [
                {"name": f"Option {index}"} for index in range(MAX_MULTI_SELECT_VALUES + 10)
            ],
        }
    }

    compacted = compact_properties(properties, page_id="page-1")

    assert compacted.truncated is False
    assert len(compacted.values["Tags"]) == MAX_MULTI_SELECT_VALUES
    assert untrusted_content_text(compacted.values["Tags"][-1]) == "Option 99"


def test_compact_properties_normalizes_formula_result_types() -> None:
    properties = {
        "Number formula": {"type": "formula", "formula": {"type": "number", "number": 18}},
        "Text formula": {
            "type": "formula",
            "formula": {"type": "string", "string": "Ready"},
        },
        "Boolean formula": {
            "type": "formula",
            "formula": {"type": "boolean", "boolean": True},
        },
        "Date formula": {
            "type": "formula",
            "formula": {
                "type": "date",
                "date": {"start": "2026-09-01", "end": None, "time_zone": None},
            },
        },
        "Empty formula": {"type": "formula", "formula": {"type": "string", "string": None}},
        "Unknown formula": {
            "type": "formula",
            "formula": {"type": "future_type", "future_type": "value"},
        },
    }

    compacted = compact_properties(properties, page_id="page-1")
    result = compacted.values

    assert compacted.truncated is False
    assert result["Number formula"] == 18
    assert untrusted_content_text(result["Text formula"]) == "Ready"
    assert result["Boolean formula"] is True
    assert result["Date formula"] == {
        "start": UntrustedNode(
            source_kind="notion_data_source",
            source_ref="page-1",
            content="2026-09-01",
        )
    }
    assert result["Empty formula"] is None
    assert result["Unknown formula"] == {"unsupported_formula_type": "future_type"}


async def test_data_source_and_empty_query_are_normalized() -> None:
    responses = [
        fixture("data_source.json"),
        {
            "results": [],
            "has_more": False,
            "next_cursor": None,
            "request_status": {"type": "complete"},
        },
    ]
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=responses.pop(0), request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = NotionClient(token, client=http_client)
        data_source = await get_data_source(client, data_source_id="source-1")
        query = await query_data_source(client, data_source_id="source-1", limit=25)

    assert untrusted_content_text(data_source["title"]) == "Projects"
    assert json.loads(requests[1].content) == {
        "page_size": 25,
        "result_type": "page",
    }
    assert query == {
        "records": [],
        "count": 0,
        "has_more": False,
        "next_cursor": None,
        "incomplete": False,
    }


async def test_query_preserves_long_provider_cursor_verbatim() -> None:
    provider_cursor = ("opaque+/=_-" * 150) + "terminal"

    def handler(request: httpx2.Request) -> httpx2.Response:
        payload = fixture("query.json")
        payload["next_cursor"] = provider_cursor
        return httpx2.Response(200, json=payload, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        result = await query_data_source(
            NotionClient(token, client=http_client),
            data_source_id="source-1",
            limit=50,
        )

    assert len(provider_cursor) > 1_000
    assert result["next_cursor"] == provider_cursor


def test_pagination_cursor_accepts_provider_bound_verbatim() -> None:
    provider_cursor = "x" * MAX_NOTION_PROVIDER_CURSOR_CHARS

    result = pagination_envelope(
        {"results": [], "has_more": True, "next_cursor": provider_cursor},
        operation="search",
    )

    assert result["next_cursor"] == provider_cursor


@pytest.mark.parametrize("cursor", ["", 42, {"cursor": "value"}])
def test_pagination_cursor_rejects_invalid_provider_values(cursor) -> None:
    with pytest.raises(IntegrationValidationError, match="invalid pagination cursor"):
        pagination_envelope(
            {"results": [], "has_more": True, "next_cursor": cursor},
            operation="search",
        )


def test_pagination_cursor_rejects_oversized_provider_value() -> None:
    with pytest.raises(IntegrationValidationError, match="invalid pagination cursor"):
        pagination_envelope(
            {
                "results": [],
                "has_more": True,
                "next_cursor": "x" * (MAX_NOTION_PROVIDER_CURSOR_CHARS + 1),
            },
            operation="search",
        )


@pytest.mark.parametrize("has_more", [None, 0, 1, "false", "true"])
def test_pagination_rejects_non_boolean_has_more(has_more) -> None:
    with pytest.raises(IntegrationValidationError, match="invalid pagination status"):
        pagination_envelope(
            {"results": [], "has_more": has_more, "next_cursor": None},
            operation="search",
        )


@pytest.mark.parametrize(
    ("has_more", "next_cursor"),
    [(True, None), (False, "cursor-2")],
)
def test_pagination_rejects_inconsistent_cursor_state(has_more, next_cursor) -> None:
    with pytest.raises(IntegrationValidationError, match="inconsistent pagination fields"):
        pagination_envelope(
            {"results": [], "has_more": has_more, "next_cursor": next_cursor},
            operation="search",
        )


@pytest.mark.parametrize(
    "request_status",
    ["complete", {}, {"type": "future_status"}],
)
def test_pagination_rejects_invalid_request_status(request_status) -> None:
    with pytest.raises(IntegrationValidationError, match="invalid request status"):
        pagination_envelope(
            {
                "results": [],
                "has_more": False,
                "next_cursor": None,
                "request_status": request_status,
            },
            operation="query_data_source",
        )


async def test_query_treats_missing_request_status_as_incomplete() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"results": [], "has_more": False, "next_cursor": None},
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        result = await query_data_source(
            NotionClient(token, client=http_client),
            data_source_id="source-1",
            limit=25,
        )

    assert result["incomplete"] is True
