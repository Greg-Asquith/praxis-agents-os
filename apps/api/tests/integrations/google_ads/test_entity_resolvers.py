"""Google Ads entity resolver, ordering, cursor, and scope contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.exceptions.general import AppValidationError
from integrations.google_ads.entity_resolvers.ad_group import (
    resolve_google_ads_ad_groups,
    search_google_ads_ad_groups,
)
from integrations.google_ads.entity_resolvers.campaign import (
    GOOGLE_ADS_CAMPAIGN_RESOLVER,
    _choice as campaign_choice,
    resolve_google_ads_campaigns,
    search_google_ads_campaigns,
)
from integrations.google_ads.entity_resolvers.shared_set import (
    _choice as shared_set_choice,
    resolve_google_ads_shared_sets,
    search_google_ads_shared_sets,
)
from integrations.google_ads.entity_resolvers.utils import group_scoped_references
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignReference,
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


def test_campaign_reference_truncates_long_name() -> None:
    choice = campaign_choice(
        SimpleNamespace(integration_resource_id=uuid4(), display_name="Ads account"),
        {"id": "10", "name": "x" * 800, "status": "ENABLED"},
    )

    assert choice is not None
    assert choice.label == "x" * 500
    assert choice.value["label"] == "x" * 500


def test_campaign_reference_rejects_removed_campaign() -> None:
    choice = campaign_choice(
        SimpleNamespace(integration_resource_id=uuid4(), display_name="Ads account"),
        {"id": "10", "name": "Removed campaign", "status": "REMOVED"},
    )

    assert choice is None


def test_scoped_reference_grouping_is_context_ordered_deduplicated_and_bounded() -> None:
    first = _writable_google_ads_entry()
    second = _writable_google_ads_entry()
    incompatible = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id="owner@example.com",
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
    assert [reference.external_id for reference in grouped[0][1]] == sorted(
        {str(index) for index in range(1, 61)}
    )[:50]
    assert [reference.external_id for reference in grouped[1][1]] == ["900"]


def test_shared_set_choice_carries_member_count() -> None:
    choice = shared_set_choice(
        SimpleNamespace(integration_resource_id=uuid4(), display_name="Ads account"),
        {"id": "50", "name": "Brand Protection", "memberCount": "312"},
    )

    assert choice is not None
    assert choice.value["entity_kind"] == "google_ads_shared_set"
    assert choice.value["member_count"] == 312
    assert choice.description == "312 negative keywords"


def test_shared_set_reference_canonicalizes_google_resource_name() -> None:
    resource_id = uuid4()

    reference = GoogleAdsSharedSetReference.model_validate(
        {
            "entity_kind": "google_ads_shared_set",
            "integration_resource_id": resource_id,
            "external_id": "customers/9308708411/sharedSets/12186751748",
            "entity_id": "12186751748",
            "label": "Testing 2",
        }
    )

    assert reference.external_id == "12186751748"
    assert "entity_id" not in reference.model_dump()


def test_shared_set_reference_rejects_conflicting_redundant_id() -> None:
    with pytest.raises(ValidationError, match="entity_id"):
        GoogleAdsSharedSetReference.model_validate(
            {
                "integration_resource_id": uuid4(),
                "external_id": "customers/9308708411/sharedSets/12186751748",
                "entity_id": "999",
                "label": "Testing 2",
            }
        )


async def test_shared_set_search_pages_every_account_without_truncation(monkeypatch) -> None:
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=uuid4(),
            provider_key="google_ads",
            resource_type="google_ads_account",
            external_id=customer_id,
            display_name=f"Account {customer_id}",
            connection_id=uuid4(),
            connection_label="Agency",
            connection_status="active",
            write_allowed=True,
            permissions_metadata={"login_customer_id": "999"},
        )
        for customer_id in ("111", "222")
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=entries),
    )
    query_calls = []

    async def query(_ctx, entry, **kwargs):
        query_calls.append((entry, kwargs))
        if entry == entries[1]:
            return [{"id": "900", "name": "Only in second", "memberCount": 1}]
        return [
            {
                "id": str(index),
                "name": f"List {index:03d}",
                "memberCount": index,
            }
            for index in range(150)
        ]

    monkeypatch.setattr("integrations.google_ads.entity_resolvers.shared_set._query", query)

    pages = []
    cursors = []
    cursor = None
    while True:
        page = await search_google_ads_shared_sets(ctx, "Brand's \\ list", {}, 25, cursor)
        pages.append(page)
        if page.next_cursor is None:
            break
        assert page.next_cursor not in cursors
        cursors.append(page.next_cursor)
        cursor = page.next_cursor

    choices = [choice for page in pages for choice in page.choices]
    identities = [
        (choice.value["integration_resource_id"], choice.value["external_id"]) for choice in choices
    ]
    assert len(choices) == 151
    assert len(identities) == len(set(identities))
    assert identities[1] == (str(entries[1].integration_resource_id), "900")
    assert all(len(page.choices) <= 25 for page in pages)
    assert pages[-1].next_cursor is None
    assert cursors == ["25", "50", "75", "100", "125", "150"]
    assert all(kwargs["search"] == "Brand's \\ list" for _, kwargs in query_calls)
    assert all(kwargs["limit"] is None for _, kwargs in query_calls)

    invalid_cursor_page = await search_google_ads_shared_sets(
        ctx, "Brand's \\ list", {}, 25, "invalid"
    )
    assert invalid_cursor_page.choices == pages[0].choices


async def test_shared_set_hydration_drops_invalid_and_inactive_ids(monkeypatch) -> None:
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
    query = AsyncMock(return_value=[{"id": "50", "name": "Current list", "memberCount": 4}])
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.shared_set._query", query)

    choices = await resolve_google_ads_shared_sets(
        ctx,
        [
            {
                "entity_kind": "google_ads_shared_set",
                "integration_resource_id": str(active.integration_resource_id),
                "external_id": "customers/111/sharedSets/50",
                "entity_id": "50",
                "label": "Current list",
            },
            GoogleAdsSharedSetReference(
                integration_resource_id=active.integration_resource_id,
                external_id="not-digits",
                label="Invalid list",
            ),
            GoogleAdsSharedSetReference(
                integration_resource_id=uuid4(),
                external_id="60",
                label="Inactive list",
            ),
        ],
        {},
    )

    assert [choice.value["external_id"] for choice in choices] == ["50"]
    assert query.await_args.kwargs["shared_set_ids"] == ["50"]
    assert query.await_args.kwargs["limit"] == 1


async def test_campaign_search_bounds_pagination_and_filters_active_scope(monkeypatch) -> None:
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
    second_active = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="222",
        display_name="Second ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"login_customer_id": "999"},
    )
    incompatible = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id="owner@example.com",
        display_name="Mailbox",
        connection_id=uuid4(),
        connection_label="Gmail",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(active, second_active, incompatible)),
    )
    query = AsyncMock(
        return_value=[
            {"id": str(index), "name": f"Campaign {index}", "status": "ENABLED"}
            for index in range(101)
        ]
    )
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.campaign._query", query)

    page = await search_google_ads_campaigns(ctx, "Campaign's \\ list", {}, 25, "100")

    assert [choice.value["external_id"] for choice in page.choices] == ["100"]
    assert page.next_cursor is None
    assert [call.args[1] for call in query.await_args_list] == [active, second_active]
    assert all(
        call.kwargs
        == {
            "search": "Campaign's \\ list",
            "limit": 101,
            "exclude_removed": True,
        }
        for call in query.await_args_list
    )


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
                integration_resource_id=active.integration_resource_id,
                external_id="10",
                label="Current campaign",
            ),
            GoogleAdsCampaignReference(
                integration_resource_id=active.integration_resource_id,
                external_id="20",
                label="Deleted campaign",
            ),
            GoogleAdsCampaignReference(
                integration_resource_id=uuid4(),
                external_id="30",
                label="Inactive account",
            ),
        ],
        {},
    )

    assert [choice.value["external_id"] for choice in choices] == ["10"]
    query.assert_awaited_once()
    assert query.await_args.kwargs == {
        "campaign_ids": ["10", "20"],
        "limit": 2,
        "exclude_removed": True,
    }


async def test_ad_group_search_fans_out_and_labels_campaign_scope(monkeypatch) -> None:
    active = _writable_google_ads_entry()
    second_active = _writable_google_ads_entry()
    incompatible = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id="owner@example.com",
        display_name="Mailbox",
        connection_id=uuid4(),
        connection_label="Gmail",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(active, second_active, incompatible)),
    )
    query = AsyncMock(
        return_value=[
            {
                "adGroup": {"id": "10", "name": "Exact", "status": "ENABLED"},
                "campaign": {"name": "Brand"},
            }
        ]
    )
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.ad_group._query", query)

    page = await search_google_ads_ad_groups(ctx, "Group's \\ name", {}, 25, None)

    assert len(page.choices) == 2
    assert [choice.value["scope_label"] for choice in page.choices] == ["Brand", "Brand"]
    assert [call.args[1] for call in query.await_args_list] == [active, second_active]
    assert all(
        call.kwargs
        == {
            "search": "Group's \\ name",
            "limit": 26,
            "exclude_removed": True,
        }
        for call in query.await_args_list
    )


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
                "campaign": {"name": "Brand"},
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
                integration_resource_id=uuid4(),
                external_id="30",
                label="Inactive ad group",
            ),
        ],
        {},
    )

    assert [choice.value["external_id"] for choice in choices] == ["10"]
    assert choices[0].value["scope_label"] == "Brand"
    assert query.await_args.kwargs == {
        "ad_group_ids": ["10", "20"],
        "limit": 2,
        "exclude_removed": True,
    }


async def test_campaign_and_ad_group_resolvers_call_canonical_operations(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(entry,)),
    )
    client = object()
    campaign_operation = AsyncMock(
        return_value=[{"id": "10", "name": "Search", "status": "ENABLED"}]
    )
    ad_group_operation = AsyncMock(
        return_value=[
            {
                "adGroup": {"id": "20", "name": "Exact", "status": "ENABLED"},
                "campaign": {"name": "Brand"},
            }
        ]
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.campaign.google_ads_client_for_principal",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.campaign.list_campaigns",
        campaign_operation,
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.ad_group.google_ads_client_for_principal",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.ad_group.list_ad_groups",
        ad_group_operation,
    )

    await resolve_google_ads_campaigns(ctx, [_campaign_reference(entry, "10")], {})
    await resolve_google_ads_ad_groups(ctx, [_ad_group_reference(entry, "20")], {})

    campaign_operation.assert_awaited_once_with(
        client,
        customer_id="111",
        login_customer_id="999",
        campaign_ids=["10"],
        search=None,
        limit=1,
        exclude_removed=True,
    )
    ad_group_operation.assert_awaited_once_with(
        client,
        customer_id="111",
        login_customer_id="999",
        ad_group_ids=["20"],
        search=None,
        limit=1,
        exclude_removed=True,
    )


async def test_google_ads_approval_canonicalization_rejects_stale_target(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    resolver_context = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(entry,)),
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
