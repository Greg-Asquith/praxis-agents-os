"""URL Inspection routing, projection, bounds, and isolation coverage."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from core.exceptions.integration import IntegrationPermissionError, IntegrationValidationError
from integrations.google_search_console.operations.inspect_url import inspect_url
from integrations.google_search_console.tools.utils.routing import url_references_for_entries
from services.agents.runtime.untrusted import (
    UNTRUSTED_CONTENT_START,
    UntrustedNode,
    render_untrusted_frames,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy

HOSTILE_REFERRER = (
    (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "prompt_injection"
        / "hostile_search_console_referring_url.txt"
    )
    .read_text(encoding="utf-8")
    .strip()
)


def _entry(site_url: str) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_search_console",
        resource_type="google_search_console_site",
        external_id=site_url,
        display_name=site_url,
        connection_id=uuid4(),
        connection_label="Search Console",
        connection_status="active",
        write_allowed=False,
    )


class _Client:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def inspection_post(self, path: str, **kwargs: Any) -> Any:
        self.calls.append((path, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_url_routing_prefers_longest_prefix_then_domain_and_preserves_order() -> None:
    entries = (
        _entry("sc-domain:example.com"),
        _entry("https://example.com/"),
        _entry("https://example.com/docs/"),
    )

    references = url_references_for_entries(
        entries,
        ["https://blog.example.com/post", "HTTPS://EXAMPLE.COM/docs/start"],
    )

    assert [reference.site_url for reference in references] == [
        "sc-domain:example.com",
        "https://example.com/docs/",
    ]
    assert [reference.url for reference in references] == [
        "https://blog.example.com/post",
        "HTTPS://EXAMPLE.COM/docs/start",
    ]


@pytest.mark.parametrize(
    ("urls", "message"),
    [
        (["ftp://example.com/file"], "HTTP or HTTPS"),
        (["https://user:secret@example.com/"], "without credentials"),
        (["https://other.test/"], "select its property"),
        (["https://example.com/", "https://example.com/"], "more than once"),
        (["https://example.com/" + "a" * 4_100], "no more than 4,096 characters"),
        ([], "at least one"),
    ],
)
def test_url_routing_rejects_invalid_unselected_and_duplicate_urls(
    urls: list[str], message: str
) -> None:
    with pytest.raises(ModelRetry, match=message):
        url_references_for_entries((_entry("https://example.com/"),), urls)


async def test_inspection_posts_every_argument_and_bounds_provider_content() -> None:
    client = _Client(
        {
            "inspectionResult": {
                "inspectionResultLink": "https://search.google.com/search-console/inspect?x=1",
                "indexStatusResult": {
                    "verdict": "PASS",
                    "coverageState": "Submitted and indexed",
                    "robotsTxtState": "ALLOWED",
                    "indexingState": "INDEXING_ALLOWED",
                    "lastCrawlTime": "2026-08-30T12:30:00Z",
                    "pageFetchState": "SUCCESSFUL",
                    "googleCanonical": "https://example.com/page",
                    "userCanonical": "https://example.com/page?canonical=1",
                    "sitemap": [f"https://example.com/{index}.xml" for index in range(25)],
                    "referringUrls": [HOSTILE_REFERRER],
                    "crawledAs": "MOBILE",
                },
                "mobileUsabilityResult": {"verdict": "PASS"},
                "richResultsResult": {
                    "verdict": "FAIL",
                    "detectedItems": [
                        {
                            "richResultType": "Product snippets",
                            "items": [
                                {"issues": [{"issueMessage": "one"}, {"issueMessage": "two"}]}
                            ],
                        }
                    ],
                },
                "ampResult": {"verdict": "PASS"},
            }
        }
    )

    result = await inspect_url(
        client,
        site_url="https://example.com/",
        url="https://example.com/page",
        language_code="en-GB",
    )

    path, call = client.calls[0]
    assert path == "urlInspection/index:inspect"
    assert call == {
        "operation": "inspect_url",
        "policy": IntegrationRequestPolicy.READ,
        "json": {
            "inspectionUrl": "https://example.com/page",
            "siteUrl": "https://example.com/",
            "languageCode": "en-GB",
        },
    }
    assert result["verdict"] == "PASS"
    assert isinstance(result["google_canonical"], UntrustedNode)
    assert isinstance(result["referring_urls"][0], UntrustedNode)
    assert result["referring_urls"][0].content == HOSTILE_REFERRER
    [rendered] = render_untrusted_frames(
        [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="google_search_console_inspect_url",
                        content=result,
                        tool_call_id="call-inspection",
                    )
                ]
            )
        ]
    )
    framed_referrer = rendered.parts[0].content["referring_urls"][0]
    assert framed_referrer.count(UNTRUSTED_CONTENT_START) == 1
    assert "IGNORE_PREVIOUS_INSTRUCTIONS" in framed_referrer
    assert len(result["sitemap"]) == 20
    assert result["rich_results"] == [{"type": "Product snippets", "issue_count": 2}]
    assert all(not key.startswith("amp") for key in result)


async def test_inspection_turns_a_provider_error_into_one_bounded_url_result() -> None:
    result = await inspect_url(
        _Client(
            IntegrationPermissionError(
                "Google rejected this URL.",
                provider_key="google_search_console",
                operation="inspect_url",
            )
        ),
        site_url="sc-domain:example.com",
        url="https://example.com/private",
        language_code="en-US",
    )

    assert result["error_code"] == "IntegrationPermissionError"
    assert isinstance(result["message"], UntrustedNode)
    assert result["message"].content == "Google rejected this URL."


@pytest.mark.parametrize("payload", [[], {}, {"inspectionResult": []}])
async def test_inspection_rejects_malformed_provider_responses(payload: Any) -> None:
    with pytest.raises(IntegrationValidationError):
        await inspect_url(
            _Client(payload),
            site_url="sc-domain:example.com",
            url="https://example.com/",
            language_code="en-US",
        )
