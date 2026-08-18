"""Google Analytics Google Ads link tool contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.google_analytics.client import GoogleAnalyticsClient
from integrations.google_analytics.operations.list_google_ads_links import (
    list_google_ads_links,
)
from integrations.google_analytics.tools.list_google_ads_links import (
    DEFINITION,
    google_analytics_list_google_ads_links,
)
from services.integrations.context.domain import ResolvedActiveContext
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.google_analytics.support import property_entry, static_token


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


@pytest.mark.parametrize("customer_id", [None, "", "123x", "123_456"])
async def test_operation_rejects_non_digit_customer_ids(customer_id: object) -> None:
    client = GoogleAnalyticsClient(static_token)
    client.admin_get = AsyncMock(return_value={"googleAdsLinks": [{"customerId": customer_id}]})

    with pytest.raises(IntegrationValidationError, match="invalid Google Ads customer id"):
        await list_google_ads_links(client, property_id="123")


async def test_tool_fans_out_and_audits_only_the_link_count(monkeypatch) -> None:
    entry = property_entry()
    audit = AsyncMock(return_value=uuid4())
    provider = AsyncMock(
        return_value={
            "links": [
                {
                    "customer_id": "1234567890",
                    "can_manage_clients": False,
                    "ads_personalization_enabled": True,
                    "created_at": None,
                }
            ],
            "link_count": 1,
        }
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_analytics.tools.list_google_ads_links.google_analytics_client",
        lambda _ctx, _entry: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_analytics.tools.list_google_ads_links.list_google_ads_links",
        provider,
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Analytics Agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name="google_analytics_list_google_ads_links",
        tool_call_id="call-ga4-links",
    )

    result = await google_analytics_list_google_ads_links(ctx)

    assert result["results"][0]["data"]["link_count"] == 1
    serialized = str(result)
    assert str(entry.integration_resource_id) not in serialized
    assert str(entry.connection_id) not in serialized
    detail = audit.await_args.kwargs["operation_detail"].model_dump(mode="json")
    assert detail["intent_groups"][0]["entity_type"] == "google_analytics_google_ads_link"
    assert detail["intent_groups"][0]["items"][0]["fields"] == {"link_count": 1}
    assert "1234567890" not in str(detail)


def test_definition_is_typed_read_auto_and_code_eligible() -> None:
    assert DEFINITION.effect == "read"
    assert DEFINITION.egress == "provider_query"
    assert DEFINITION.default_policy == "auto"
    assert DEFINITION.code_eligible is True
    assert DEFINITION.timeout == 30
    assert DEFINITION.output_model is not None
    assert DEFINITION.presentation.arg_fields == ()
    assert "sessionGoogleAdsCustomerId" in DEFINITION.description


async def _async_value(value):
    return value
