# apps/api/tests/services/web/test_page_speed.py

"""What measure_page_speed sends to PageSpeed Insights and how it reduces the response."""

import httpx2
import pytest

from services.web.page_speed import (
    REPORT_MAX_BYTES,
    PageSpeedError,
    reduce_page_speed,
    report_json,
)
from tests.support.web import fake_page_speed, page_speed_response

_URL = "https://shop.example/"


async def test_a_test_sends_the_key_in_a_header_and_reduces_the_report() -> None:
    requests: list[httpx2.Request] = []
    run = fake_page_speed(
        lambda _request: httpx2.Response(200, json=page_speed_response(_URL)), requests=requests
    )

    test = await run(
        _URL,
        strategy="mobile",
        categories=("performance", "accessibility"),
        api_key="secret-key",
        timeout_seconds=5,
    )

    [request] = requests
    assert request.headers["x-goog-api-key"] == "secret-key"
    assert "secret-key" not in str(request.url)
    assert request.url.params.multi_items() == [
        ("url", _URL),
        ("strategy", "MOBILE"),
        ("category", "PERFORMANCE"),
        ("category", "ACCESSIBILITY"),
    ]
    summary = test.summary
    assert summary["final_url"] is None
    assert summary["scores"] == {"performance": 48, "accessibility": 91}
    assert summary["lab"] == {
        "lcp_ms": 4622,
        "cls": 0.042,
        "tbt_ms": 352,
        "fcp_ms": 2810,
        "speed_index_ms": 5100,
    }
    # INP is rated needs improvement, so the page fails even though LCP and CLS are good.
    assert summary["field"]["inp_ms"] == {"p75": 260, "rating": "needs_improvement"}
    assert summary["field"]["cls"] == {"p75": 0.05, "rating": "good"}
    assert summary["field"]["core_web_vitals"] == "failed"
    assert test.origin_field["core_web_vitals"] == "passed"
    # Ranked by time saved, then bytes saved.
    assert [issue["audit"] for issue in summary["top_issues"]] == [
        "render-blocking-resources",
        "unused-javascript",
        "mainthread-work-breakdown",
    ]
    report = test.report
    assert [audit["id"] for audit in report["failed_audits"]] == [
        "render-blocking-resources",
        "unused-javascript",
        "uses-optimized-images",
        "mainthread-work-breakdown",
        "image-alt",
    ]
    assert report["failed_audits"][1]["items"][1] == {
        "url": "https://www.googletagmanager.example/gtag/js?id=G-TEST",
        "total_bytes": 140200,
        "wasted_bytes": 66100,
        "entity": "Google Tag Manager",
    }
    assert report["lcp_element"]["selector"] == "main > img.hero"
    assert [party["entity"] for party in report["third_parties"]] == [
        "Google Tag Manager",
        "Example Reviews",
    ]
    assert report["passed_audits"] == ["uses-text-compression", "color-contrast"]
    assert "data:image" not in report_json(report)


def test_a_large_report_is_cut_to_the_byte_limit_items_first() -> None:
    response = page_speed_response(_URL)
    audits = response["lighthouseResult"]["audits"]
    refs = response["lighthouseResult"]["categories"]["performance"]["auditRefs"]
    item = {"url": "https://shop.example/" + "a" * 480, "totalBytes": 1, "wastedBytes": 1}
    for index in range(60):
        audits[f"bulky-{index}"] = {
            "title": "Bulky",
            "description": "d" * 600,
            "score": 0,
            "scoreDisplayMode": "binary",
            "details": {"type": "table", "items": [item] * 30},
        }
        refs.append({"id": f"bulky-{index}", "group": "diagnostics"})

    report = reduce_page_speed(
        response, requested_url=_URL, strategy="mobile", categories=("performance",)
    ).report

    assert len(report_json(report)) <= REPORT_MAX_BYTES
    assert report["truncated"]
    assert report["failed_audits"][0]["id"] == "render-blocking-resources"
    assert report["failed_audits"][-1]["item_count"] == 30
    assert report["failed_audits"][-1]["items"] == []


async def test_private_and_denylisted_urls_are_refused_before_google_is_called() -> None:
    requests: list[httpx2.Request] = []
    run = fake_page_speed(lambda _request: httpx2.Response(500), requests=requests)

    errors = []
    for url in ("http://10.0.0.8/admin", "https://www.blocked.example/"):
        with pytest.raises(PageSpeedError) as raised:
            await run(
                url,
                strategy="mobile",
                categories=("performance",),
                api_key="secret-key",
                timeout_seconds=5,
                blocked_domains=("blocked.example",),
            )
        errors.append(raised.value.error_class)

    assert errors == ["non_public_address", "blocked_domain"]
    assert requests == []


@pytest.mark.parametrize(
    ("response", "error_class"),
    [
        (
            httpx2.Response(
                500,
                json={
                    "error": {
                        "code": 500,
                        "message": "Lighthouse returned error: FAILED_DOCUMENT_REQUEST. Lighthouse "
                        "was unable to reliably load the page you requested.",
                    }
                },
            ),
            "page_unreachable",
        ),
        (
            httpx2.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "message": "API key not valid. Please pass a valid API key.",
                    }
                },
            ),
            "key_rejected",
        ),
        (
            httpx2.Response(429, json={"error": {"code": 429, "message": "Quota exceeded."}}),
            "quota_exceeded",
        ),
    ],
)
async def test_google_errors_map_to_error_classes(
    response: httpx2.Response, error_class: str
) -> None:
    run = fake_page_speed(lambda _request: response)

    with pytest.raises(PageSpeedError) as raised:
        await run(
            _URL,
            strategy="desktop",
            categories=("performance",),
            api_key="secret-key",
            timeout_seconds=5,
        )

    assert raised.value.error_class == error_class
