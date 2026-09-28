"""Google Ads entity resolver, ordering, cursor, and scope contracts."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.exceptions.general import AppValidationError
from integrations.google_ads.entity_resolvers.ad_group import (
    resolve_google_ads_ad_groups,
)
from integrations.google_ads.entity_resolvers.campaign import (
    GOOGLE_ADS_CAMPAIGN_RESOLVER,
    resolve_google_ads_campaigns,
)
from integrations.google_ads.entity_resolvers.campaign_budget import (
    resolve_google_ads_campaign_budgets,
    search_google_ads_campaign_budgets,
)
from integrations.google_ads.entity_resolvers.keyword import (
    resolve_google_ads_keywords,
)
from integrations.google_ads.entity_resolvers.recommendation import (
    search_google_ads_recommendations,
)
from integrations.google_ads.entity_resolvers.shared_set import (
    search_google_ads_shared_sets,
)
from integrations.google_ads.entity_resolvers.utils import (
    GoogleAdsEntityCursor,
    decode_entity_cursor,
    encode_entity_cursor,
    entity_search_fingerprint,
    group_scoped_references,
)
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignBudgetReference,
    GoogleAdsCampaignReference,
    GoogleAdsKeywordReference,
    GoogleAdsSharedSetReference,
)
from integrations.google_ads.tools.update_campaign_status import (
    DEFINITION as GOOGLE_ADS_UPDATE_CAMPAIGN_STATUS_DEFINITION,
)
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
)
from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from tests.integrations.google_ads.support import (
    _ad_group_reference,
    _campaign_reference,
    _writable_google_ads_entry,
)


async def test_keyword_hydration_keeps_composite_provider_identity(monkeypatch) -> None:
    active = _writable_google_ads_entry()
    ctx = SimpleNamespace(active_context=ResolvedActiveContext(entries=(active,)))
    references = [
        GoogleAdsKeywordReference(
            customer_id=active.external_id,
            campaign_id="1",
            ad_group_id=ad_group_id,
            criterion_id="90",
            text="running shoes",
            match_type="EXACT",
            status="PAUSED",
            label="running shoes",
        )
        for ad_group_id in ("20", "30")
    ]

    async def query(_ctx, _entry, **_kwargs):
        return [
            {
                "campaign": {"id": "1", "name": "Brand"},
                "adGroup": {"id": reference.ad_group_id, "name": "Shoes"},
                "adGroupCriterion": {
                    "criterionId": reference.criterion_id,
                    "status": reference.status,
                    "keyword": {"text": reference.text, "matchType": reference.match_type},
                },
            }
            for reference in references
        ]

    monkeypatch.setattr("integrations.google_ads.entity_resolvers.keyword._query", query)

    choices = await resolve_google_ads_keywords(ctx, references, {})

    assert [reference.provider_entity_id for reference in references] == ["20~90", "30~90"]
    assert [choice.value["ad_group_id"] for choice in choices] == ["20", "30"]


async def test_campaign_budget_resolver_searches_and_hydrates_live_references(
    monkeypatch,
) -> None:
    selected = _writable_google_ads_entry()
    ctx = SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,)))
    row = {
        "id": "55",
        "name": "Launch budget",
        "status": "ENABLED",
        "period": "DAILY",
        "deliveryMethod": "STANDARD",
        "amountMicros": "12500000",
        "explicitlyShared": False,
        "referenceCount": "0",
        "currencyCode": "GBP",
        "campaignLabels": (),
    }
    query = AsyncMock(return_value=[row])
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.campaign_budget._query",
        query,
    )

    page = await search_google_ads_campaign_budgets(ctx, "launch", {}, 10, None)
    resolved = await resolve_google_ads_campaign_budgets(
        ctx,
        [
            GoogleAdsCampaignBudgetReference(
                customer_id=selected.external_id,
                budget_id="55",
                label="Old name",
            )
        ],
        {},
    )

    assert [choice.label for choice in page.choices] == ["Launch budget"]
    assert resolved[0].value["amount_micros"] == "12500000"
    assert query.await_args_list[0].kwargs["search"] == "launch"
    assert query.await_args_list[1].kwargs["budget_ids"] == ["55"]


async def test_recommendation_pages_interleave_every_active_account(monkeypatch) -> None:
    first = _writable_google_ads_entry()
    second = replace(
        first,
        integration_resource_id=uuid4(),
        external_id="222",
        connection_id=uuid4(),
    )
    ctx = SimpleNamespace(active_context=ResolvedActiveContext(entries=(first, second)))

    async def query(_ctx, entry, *, limit, **_kwargs):
        return [
            {
                "resourceName": f"customers/{entry.external_id}/recommendations/r{index}",
                "type": "CAMPAIGN_BUDGET",
                "dismissed": False,
            }
            for index in range(min(limit, 4))
        ]

    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.recommendation._query",
        query,
    )

    first_page = await search_google_ads_recommendations(ctx, "", {}, 2, None)
    second_page = await search_google_ads_recommendations(ctx, "", {}, 2, first_page.next_cursor)

    assert [choice.value["customer_id"] for choice in first_page.choices] == ["111", "222"]
    assert [choice.value["resource_name"] for choice in second_page.choices] == [
        "customers/111/recommendations/r1",
        "customers/222/recommendations/r1",
    ]


def test_scoped_reference_grouping_is_context_ordered_deduplicated_and_bounded() -> None:
    first = _writable_google_ads_entry()
    second = replace(
        first,
        integration_resource_id=uuid4(),
        external_id="222",
        connection_id=uuid4(),
    )
    incompatible = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id="333",
        display_name="Mailbox",
        connection_id=uuid4(),
        connection_label="Gmail",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(first, incompatible, second))
    )
    values = [
        _campaign_reference(second, "900"),
        *(_campaign_reference(first, str(index)) for index in range(60, 0, -1)),
        _campaign_reference(first, "10"),
        _campaign_reference(incompatible, "800"),
        {"not": "a reference"},
    ]

    grouped = group_scoped_references(
        ctx,
        GOOGLE_ADS_BINDING,
        values,
        GoogleAdsCampaignReference,
    )

    assert [entry for entry, _references in grouped] == [first, second]
    assert [reference.campaign_id for reference in grouped[0][1]] == sorted(
        {str(index) for index in range(1, 61)}
    )[:50]
    assert [reference.campaign_id for reference in grouped[1][1]] == ["900"]


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "2.0000000000000000.1.00000000000000000000000000000001",
    ],
)
def test_entity_cursor_malformed_negative_and_oversized_values_restart(cursor: str) -> None:
    resource_id = UUID(int=1)

    assert (
        decode_entity_cursor(
            cursor,
            search="sale",
            integration_resource_ids=(resource_id,),
        )
        is None
    )


def test_entity_cursor_search_and_active_context_fingerprints_fail_closed() -> None:
    resource_id = UUID(int=1)
    cursor = encode_entity_cursor(
        GoogleAdsEntityCursor(
            fingerprint=entity_search_fingerprint("sale", (resource_id,)),
            last_entity_id=10,
            last_integration_resource_id=resource_id,
        )
    )

    assert (
        decode_entity_cursor(
            cursor,
            search="different",
            integration_resource_ids=(resource_id,),
        )
        is None
    )
    assert (
        decode_entity_cursor(
            cursor,
            search="sale",
            integration_resource_ids=(UUID(int=2),),
        )
        is None
    )


def test_shared_set_reference_rejects_internal_or_legacy_ids() -> None:
    with pytest.raises(ValidationError, match="integration_resource_id"):
        GoogleAdsSharedSetReference.model_validate(
            {
                "customer_id": "9308708411",
                "shared_set_id": "12186751748",
                "integration_resource_id": uuid4(),
                "label": "Testing 2",
            }
        )


async def test_shared_set_tie_cursor_uses_exclusive_then_inclusive_account_boundaries(
    monkeypatch,
) -> None:
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=UUID(int=index),
            provider_key="google_ads",
            resource_type="google_ads_account",
            external_id=str(index),
            display_name=f"Account {index}",
            connection_id=uuid4(),
            connection_label="Agency",
            connection_status="active",
            write_allowed=True,
            permissions_metadata={"login_customer_id": "999"},
        )
        for index in (1, 2)
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=entries),
    )
    query = AsyncMock(return_value=[{"id": "10", "name": "Same ID", "memberCount": 1}])
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.shared_set._query", query)

    first = await search_google_ads_shared_sets(ctx, "", {}, 1, None)
    second = await search_google_ads_shared_sets(ctx, "", {}, 1, first.next_cursor)

    assert first.choices[0].value["customer_id"] == entries[0].external_id
    assert second.choices[0].value["customer_id"] == entries[1].external_id
    continuation_calls = query.await_args_list[2:]
    assert continuation_calls[0].kwargs["minimum_id"] == 10
    assert continuation_calls[0].kwargs["minimum_id_inclusive"] is False
    assert continuation_calls[1].kwargs["minimum_id"] == 10
    assert continuation_calls[1].kwargs["minimum_id_inclusive"] is True


async def test_campaign_hydration_rejects_stale_and_inactive_scope(monkeypatch) -> None:
    active = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"login_customer_id": "999"},
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(active,)),
    )
    query = AsyncMock(return_value=[{"id": "10", "name": "Current campaign", "status": "ENABLED"}])
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.campaign._query", query)

    choices = await resolve_google_ads_campaigns(
        ctx,
        [
            GoogleAdsCampaignReference(
                customer_id=active.external_id,
                campaign_id="10",
                label="Current campaign",
            ),
            GoogleAdsCampaignReference(
                customer_id=active.external_id,
                campaign_id="20",
                label="Deleted campaign",
            ),
            GoogleAdsCampaignReference(
                customer_id="999",
                campaign_id="30",
                label="Inactive account",
            ),
        ],
        {},
    )

    assert [choice.value["campaign_id"] for choice in choices] == ["10"]
    query.assert_awaited_once()
    assert query.await_args.kwargs == {
        "campaign_ids": ["10", "20"],
        "limit": 2,
        "exclude_removed": True,
    }


async def test_ad_group_hydration_drops_stale_and_out_of_context_values(monkeypatch) -> None:
    active = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(active,)),
    )
    query = AsyncMock(
        return_value=[
            {
                "adGroup": {"id": "10", "name": "Exact", "status": "ENABLED"},
                "campaign": {"id": "1", "name": "Brand"},
            }
        ]
    )
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.ad_group._query", query)

    choices = await resolve_google_ads_ad_groups(
        ctx,
        [
            _ad_group_reference(active, "10"),
            _ad_group_reference(active, "20"),
            GoogleAdsAdGroupReference(
                customer_id="999",
                campaign_id="1",
                ad_group_id="30",
                label="Inactive ad group",
            ),
        ],
        {},
    )

    assert [choice.value["ad_group_id"] for choice in choices] == ["10"]
    assert choices[0].value["scope_label"] == "Brand"
    assert query.await_args.kwargs == {
        "ad_group_ids": ["10", "20"],
        "limit": 2,
        "exclude_removed": True,
    }


async def test_google_ads_approval_canonicalization_rejects_stale_target(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    resolver_context = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(entry,)),
        tool_definition=GOOGLE_ADS_UPDATE_CAMPAIGN_STATUS_DEFINITION,
    )
    reference = _campaign_reference(entry, "10").model_dump(mode="json")
    authorized = SimpleNamespace(
        context=resolver_context,
        resolver=GOOGLE_ADS_CAMPAIGN_RESOLVER,
        field_key="campaign_ids",
        entity_kind="google_ads_campaign",
        depends_on=(),
    )
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: GOOGLE_ADS_UPDATE_CAMPAIGN_STATUS_DEFINITION,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field",
        AsyncMock(return_value=authorized),
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.campaign._query",
        AsyncMock(return_value=[]),
    )

    with pytest.raises(AppValidationError, match="unavailable or no longer accessible"):
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(conversation_id=uuid4()),
            tool_call=SimpleNamespace(
                tool_name="google_ads_update_campaign_status",
                args={"campaign_ids": [reference], "status": "PAUSED"},
            ),
            override_args=None,
        )
