# apps/api/tests/integrations/outlook_mail/test_outlook_read_operations.py

"""Outlook read request bounds, provider failures, and content provenance."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationValidationError,
)
from integrations.outlook_mail.operations.get_attachment import get_attachment
from integrations.outlook_mail.operations.get_message import get_message
from integrations.outlook_mail.operations.list_mail_folders import list_mail_folders
from integrations.outlook_mail.operations.resolve_folder import resolve_folder
from integrations.outlook_mail.operations.search_messages import search_messages
from integrations.outlook_mail.operations.search_people import search_people
from integrations.outlook_mail.settings import outlook_mail_settings
from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.microsoft_graph import MicrosoftGraphClient, fixed_access_token
from tests.support.documents import tiny_docx, tiny_pdf


@asynccontextmanager
async def graph(handler):
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        yield MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="outlook_mail", client=transport
        )


@pytest.mark.parametrize("query", [None, 'subject:"Monthly report"', 'subject:"Réunion"'])
async def test_search_unread_filters_and_bounds(query):
    def handler(request):
        assert request.url.path == "/v1.0/me/mailFolders/inbox/messages"
        assert request.headers["Prefer"] == 'IdType="ImmutableId"'
        params = request.url.params
        assert "body" not in params["$select"].split(",")
        if query:
            assert json.loads(params["$search"]) == query
            assert "\\u" not in params["$search"]
            assert "$filter" not in params and "$orderby" not in params
            assert params["$top"] == "4"
        else:
            assert params["$filter"].startswith("receivedDateTime ge ")
            assert params["$filter"].endswith("and isRead eq false")
            assert params["$orderby"] == "receivedDateTime desc"
        return httpx2.Response(
            200,
            json={
                "value": [
                    {"id": str(i), "isRead": bool(i % 2) if query else False, "subject": "x" * 600}
                    for i in range(10)
                ]
            },
        )

    async with graph(handler) as client:
        result = await search_messages(client, query=query, unread_only=True, limit=2)
    assert len(result) == 2
    assert [item["message_id"] for item in result] == (["0", "2"] if query else ["0", "1"])
    assert all(isinstance(item["subject"], UntrustedNode) for item in result)
    assert len(result[0]["subject"].content) == 500


async def test_folder_bounds_and_exact_resolution():
    def handler(request):
        assert request.url.params["$top"] == "200"
        return httpx2.Response(
            200,
            json={
                "value": [
                    {"id": str(i), "displayName": "Invoices" if i < 2 else "Other"}
                    for i in range(250)
                ]
            },
        )

    async with graph(handler) as client:
        assert len(await list_mail_folders(client)) == 200
        assert await resolve_folder(client, folder="Invoices") == "0"
        with pytest.raises(IntegrationNotFoundError):
            await resolve_folder(client, folder="invoices")


@pytest.mark.parametrize("html", [False, True])
async def test_read_bounds_and_html_fallback(html):
    def handler(request):
        if request.url.path.endswith("/attachments"):
            assert "contentBytes" not in request.url.params["$select"]
            return httpx2.Response(
                200,
                json={
                    "value": [
                        {
                            "id": str(i),
                            "name": "report.pdf",
                            "size": 5,
                            "contentType": "application/pdf",
                        }
                        for i in range(60)
                    ]
                },
            )
        assert 'outlook.body-content-type="text"' in request.headers["Prefer"]
        return httpx2.Response(
            200,
            json={
                "subject": "Report",
                "from": {"emailAddress": {"address": "dana@example.com"}},
                "toRecipients": [{"emailAddress": {"name": "Dana"}}] * 60,
                "ccRecipients": [{"emailAddress": {"name": "Kai"}}] * 60,
                "receivedDateTime": "2026-09-08T10:00:00+01:00",
                "body": {
                    "contentType": "html" if html else "text",
                    "content": "<p>" + "x" * 50001 + "</p>" if html else "x" * 50001,
                },
            },
        )

    async with graph(handler) as client:
        result = await get_message(client, message_id="message/id")
    assert len(result["body"].content) == 50000
    assert "<p>" not in result["body"].content
    assert result["truncated"] is True
    assert len(result["to"]) == len(result["cc"]) == len(result["attachments"]) == 50
    assert result["received_at"] == "2026-09-08T09:00:00Z"
    assert result["from"]["address"].source_kind == "outlook_message"
    for key in ("subject", "body", "conversation_id", "internet_message_id", "web_link"):
        assert isinstance(result[key], UntrustedNode)


@pytest.mark.parametrize("empty", [False, True])
async def test_people_bounds_and_provenance(empty):
    def handler(request):
        body = json.loads(request.content)
        assert request.method == "POST"
        assert body["requests"][0]["size"] == 2
        assert body["requests"][0]["query"]["queryString"] == "Dana"
        return httpx2.Response(
            200,
            json={
                "value": [
                    {
                        "hitsContainers": [
                            {
                                "hits": []
                                if empty
                                else [
                                    {
                                        "resource": {
                                            "displayName": "Dana" * 200,
                                            "emailAddresses": [{"address": "dana@example.com"}],
                                            "jobTitle": "Analyst",
                                            "department": "Operations",
                                        }
                                    }
                                ]
                                * 10
                            }
                        ]
                    }
                ]
            },
        )

    async with graph(handler) as client:
        people = await search_people(client, query="Dana", limit=2)
    assert len(people) == (0 if empty else 2)
    for person in people:
        assert all(isinstance(value, UntrustedNode) for value in person.values())
        assert person["name"].source_kind == "outlook_person"
        assert len(person["name"].content) == 500


@pytest.mark.parametrize(
    "status,code,error",
    [
        (404, "ErrorItemNotFound", IntegrationNotFoundError),
        (403, "ErrorAccessDenied", IntegrationPermissionError),
    ],
)
async def test_provider_errors(status, code, error):
    async with graph(
        lambda _: httpx2.Response(status, json={"error": {"code": code, "message": "private"}})
    ) as client:
        with pytest.raises(error):
            await search_messages(client)


async def test_search_rate_limit_retries(monkeypatch):
    from services.integrations import http

    requests, delays = [], []

    async def sleep(delay):
        delays.append(delay)

    def handler(request):
        requests.append(request)
        return (
            httpx2.Response(429, headers={"Retry-After": "2"})
            if len(requests) == 1
            else httpx2.Response(200, json={"value": []})
        )

    monkeypatch.setattr(http.asyncio, "sleep", sleep)
    async with graph(handler) as client:
        assert await search_messages(client) == []
    assert len(requests) == 2 and delays == [2.0]


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"@odata.type": "#microsoft.graph.itemAttachment"}, "unsupported_attachment_kind"),
        ({"@odata.type": "#microsoft.graph.referenceAttachment"}, "unsupported_attachment_kind"),
        ({"contentType": "image/png"}, "unsupported_attachment_type"),
        ({"size": 101}, "attachment_too_large"),
        ({"size": "4"}, "invalid_attachment_size"),
    ],
)
async def test_attachment_rejects_before_download(monkeypatch, changes, code):
    monkeypatch.setattr(outlook_mail_settings, "OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES", 100)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(
            200,
            json={
                "@odata.type": "#microsoft.graph.fileAttachment",
                "contentType": "text/plain",
                "size": 4,
                **changes,
            },
        )

    async with graph(handler) as client:
        with pytest.raises(IntegrationValidationError) as caught:
            await get_attachment(client, message_id="message", attachment_id="attachment")
    assert caught.value.error_code == code
    assert len(requests) == 1


async def test_attachment_download_and_unicode_boundary():
    def handler(request):
        if request.url.path.endswith("/$value"):
            assert request.headers["Authorization"] == "Bearer token"
            return httpx2.Response(200, content=("界" * 30000).encode())
        return httpx2.Response(
            200,
            json={
                "@odata.type": "#microsoft.graph.fileAttachment",
                "contentType": "text/plain",
                "name": "report.txt",
                "size": 90000,
            },
        )

    async with graph(handler) as client:
        result = await get_attachment(client, message_id="message", attachment_id="attachment")
    assert len(result["markdown"].content.encode()) <= 65536
    assert result["truncated"] is True
    assert result["source"] == "text"
    assert result["markdown"].source_ref == "message"


@pytest.mark.parametrize(
    "data,content_type,name,expected",
    [
        (tiny_pdf("Invoice total"), "application/pdf", "invoice.pdf", "Invoice total"),
        (
            tiny_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "report.docx",
            "Quarterly Results",
        ),
    ],
)
async def test_attachment_converts_real_documents(data, content_type, name, expected):
    def handler(request):
        if request.url.path.endswith("/$value"):
            return httpx2.Response(200, content=data)
        return httpx2.Response(
            200,
            json={
                "@odata.type": "#microsoft.graph.fileAttachment",
                "contentType": content_type,
                "name": name,
                "size": len(data),
            },
        )

    async with graph(handler) as client:
        result = await get_attachment(client, message_id="message", attachment_id="attachment")
    assert expected in result["markdown"].content
    assert result["source"] == "converted"


async def test_hostile_body_retains_provenance():
    hostile = (
        Path(__file__).parents[2] / "fixtures/prompt_injection/hostile_email_body.txt"
    ).read_text()

    def handler(request):
        return httpx2.Response(
            200,
            json={"value": []}
            if request.url.path.endswith("/attachments")
            else {
                "id": "message",
                "body": {"contentType": "text", "content": hostile},
            },
        )

    async with graph(handler) as client:
        result = await get_message(client, message_id="message")
    assert result["body"].content == hostile
    assert result["body"].source_kind == "outlook_message"


async def test_preview_passes_raw_html_to_engine(monkeypatch):
    from integrations.outlook_mail.operations import preview_message

    html = "<p>Message</p><script>private()</script>"

    def handler(request):
        assert request.url.params["$select"].startswith("body,")
        return httpx2.Response(
            200, json={"subject": "Report", "body": {"contentType": "html", "content": html}}
        )

    async with graph(handler) as client:
        monkeypatch.setattr(
            preview_message, "graph_client_for_connection", lambda *_args, **_kwargs: client
        )
        result = await preview_message.fetch_message_preview(object(), object(), "message")
    assert result.content == html
    assert result.content_type == "html"
    assert result.meta["subject"] == "Report"
