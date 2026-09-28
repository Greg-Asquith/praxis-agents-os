"""Google Analytics Google Ads link tool contracts."""

from unittest.mock import AsyncMock

import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.google_analytics.client import GoogleAnalyticsClient
from integrations.google_analytics.operations.list_google_ads_links import (
    list_google_ads_links,
)
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.google_analytics.support import static_token


async def test_operation_pages_and_returns_only_bounded_link_fields() -> None:
    calls: list[dict[str, object]] = []

    async def admin_get(path: str, **kwargs):
        assert path == "properties/123/googleAdsLinks"
        assert kwargs["policy"] is IntegrationRequestPolicy.READ
        calls.append(kwargs["params"])
        if "pageToken" not in kwargs["params"]:
            return {
                "googleAdsLinks": [
                    {
                        "name": "properties/123/googleAdsLinks/1",
                        "customerId": "123-456-7890",
                        "canManageClients": True,
                        "adsPersonalizationEnabled": False,
                        "createTime": "2026-08-17T09:30:00Z",
                        "creatorEmailAddress": "private@example.com",
                        "updateTime": "2026-08-17T10:00:00Z",
                    }
                ],
                "nextPageToken": "page-2",
            }
        return {
            "googleAdsLinks": [
                {
                    "customerId": " 987 654 3210 ",
                    "canManageClients": False,
                    "adsPersonalizationEnabled": True,
                }
            ]
        }

    client = GoogleAnalyticsClient(static_token)
    client.admin_get = admin_get

    result = await list_google_ads_links(client, property_id="123")

    assert result == {
        "links": [
            {
                "customer_id": "1234567890",
                "can_manage_clients": True,
                "ads_personalization_enabled": False,
                "created_at": "2026-08-17T09:30:00Z",
            },
            {
                "customer_id": "9876543210",
                "can_manage_clients": False,
                "ads_personalization_enabled": True,
                "created_at": None,
            },
        ],
        "link_count": 2,
    }
    assert calls == [
        {"pageSize": 200},
        {"pageSize": 200, "pageToken": "page-2"},
    ]
    assert "creatorEmailAddress" not in str(result)
    assert "updateTime" not in str(result)


async def test_operation_accepts_empty_links_and_enforces_five_page_cap() -> None:
    client = GoogleAnalyticsClient(static_token)
    client.admin_get = AsyncMock(return_value={"googleAdsLinks": []})
    assert await list_google_ads_links(client, property_id="123") == {
        "links": [],
        "link_count": 0,
    }

    page = 0

    async def endless_pages(*_args, **_kwargs):
        nonlocal page
        page += 1
        return {"googleAdsLinks": [], "nextPageToken": f"page-{page}"}

    client.admin_get = endless_pages
    with pytest.raises(IntegrationValidationError, match="page limit"):
        await list_google_ads_links(client, property_id="123")
    assert page == 5


@pytest.mark.parametrize(
    "customer_id",
    [
        None,
    ],
)
async def test_operation_rejects_non_digit_customer_ids(customer_id: object) -> None:
    client = GoogleAnalyticsClient(static_token)
    client.admin_get = AsyncMock(return_value={"googleAdsLinks": [{"customerId": customer_id}]})

    with pytest.raises(IntegrationValidationError, match="invalid Google Ads customer id"):
        await list_google_ads_links(client, property_id="123")


async def _async_value(value):
    return value
