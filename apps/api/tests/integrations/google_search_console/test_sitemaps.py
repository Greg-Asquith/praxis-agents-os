# apps/api/tests/integrations/google_search_console/test_sitemaps.py

"""Sitemap listing request and bounded response coverage."""

import json
from pathlib import Path
from typing import Any

import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.google_search_console.operations.list_sitemaps import list_sitemaps
from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.http import IntegrationRequestPolicy

FIXTURE = json.loads(
    (Path(__file__).with_name("fixtures") / "sitemaps.json").read_text(encoding="utf-8")
)


class _Client:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def webmasters_get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append((path, kwargs))
        return self.payload


async def test_list_sitemaps_sorts_bounds_and_drops_deprecated_indexed_counts() -> None:
    client = _Client(FIXTURE)

    result = await list_sitemaps(client, site_url="https://example.com/")

    path, call = client.calls[0]
    assert path == "sites/https%3A%2F%2Fexample.com%2F/sitemaps"
    assert call == {"operation": "list_sitemaps", "policy": IntegrationRequestPolicy.READ}
    assert result["sitemap_count"] == 2
    latest = result["sitemaps"][0]
    assert isinstance(latest["path"], UntrustedNode)
    assert latest["path"].content.endswith("latest.xml")
    assert latest["submitted_url_count"] == 5
    assert latest["is_pending"] is True
    assert "indexed" not in latest["contents"][0]


async def test_list_sitemaps_caps_results_at_200() -> None:
    payload = {
        "sitemap": [
            {
                "path": f"https://example.com/{index}.xml",
                "lastSubmitted": f"2026-08-{(index % 28) + 1:02d}T10:00:00Z",
            }
            for index in range(205)
        ]
    }
    result = await list_sitemaps(_Client(payload), site_url="https://example.com/")
    assert len(result["sitemaps"]) == 200
    assert result["sitemap_count"] == 200


@pytest.mark.parametrize("payload", [[], {"sitemap": "bad"}, {"sitemap": [None]}])
async def test_list_sitemaps_rejects_malformed_provider_responses(payload: Any) -> None:
    with pytest.raises(IntegrationValidationError):
        await list_sitemaps(_Client(payload), site_url="https://example.com/")
