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
from integrations.google_ads.entity_resolvers.utils import (
    GoogleAdsEntityCursor,
    decode_entity_cursor,
    encode_entity_cursor,
    entity_search_fingerprint,
    group_scoped_references,
)
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
        SimpleNamespace(external_id="111", display_name="Ads account"),
        {"id": "10", "name": "x" * 800, "status": "ENABLED"},
    )

    assert choice is not None
    assert choice.label == "x" * 500
    assert choice.value["label"] == "x" * 500


def test_campaign_reference_rejects_removed_campaign() -> None:
    choice = campaign_choice(
        SimpleNamespace(external_id="111", display_name="Ads account"),
        {"id": "10", "name": "Removed campaign", "status": "REMOVED"},
    )

    assert choice is None


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


def test_entity_cursor_round_trips_at_worst_case_within_generic_bound() -> None:
    resource_ids = (UUID(int=1), UUID(int=(1 << 128) - 1))
    fingerprint = entity_search_fingerprint("  Sale  ", resource_ids)
    cursor = GoogleAdsEntityCursor(
        fingerprint=fingerprint,
        last_entity_id=(1 << 63) - 1,
        last_integration_resource_id=resource_ids[-1],
    )

    encoded = encode_entity_cursor(cursor)

    assert len(encoded) <= 128
    assert (
        decode_entity_cursor(
            encoded,
            search="Sale",
            integration_resource_ids=resource_ids,
        )
        == cursor
    )


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "2.0000000000000000.1.00000000000000000000000000000001",
        "1.0000000000000000.-1.00000000000000000000000000000001",
        f"1.0000000000000000.{1 << 63}.00000000000000000000000000000001",
        "1.not-a-fingerprint.1.00000000000000000000000000000001",
        "x" * 129,
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


def test_shared_set_choice_carries_member_count() -> None:
    choice = shared_set_choice(
        SimpleNamespace(external_id="111", display_name="Ads account"),
        {"id": "50", "name": "Brand Protection", "memberCount": "312"},
    )

    assert choice is not None
    assert choice.value["entity_kind"] == "google_ads_shared_set"
    assert choice.value["member_count"] == 312
    assert choice.description == "312 negative keywords"


def test_shared_set_reference_canonicalizes_google_resource_name() -> None:
    reference = GoogleAdsSharedSetReference.model_validate(
        {
            "entity_kind": "google_ads_shared_set",
            "customer_id": "930-870-8411",
            "shared_set_id": "customers/9308708411/sharedSets/12186751748",
            "label": "Testing 2",
        }
    )

    assert reference.shared_set_id == "12186751748"
    assert reference.customer_id == "9308708411"


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


def test_customer_id_rejects_non_digit_values_at_validation() -> None:
    with pytest.raises(ValidationError, match="customer_id"):
        GoogleAdsSharedSetReference.model_validate(
            {
                "customer_id": "customers/9308708411",
                "shared_set_id": "12186751748",
                "label": "Testing 2",
            }
        )


async def test_shared_set_search_uses_global_tuple_order_and_reaches_every_account(
    monkeypatch,
) -> None:
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=UUID(int=index),
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
        for index, customer_id in enumerate(("111", "222"), start=1)
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=entries),
    )
    rows_by_resource = {
        entries[0].integration_resource_id: (1, 2, 4, 7, 9, 11, 11),
        entries[1].integration_resource_id: (1, 3, 4, 5),
    }
    query_calls: list[tuple[ResolvedContextEntry, dict]] = []

    async def query(_ctx, entry, **kwargs):
        query_calls.append((entry, kwargs))
        minimum_id = kwargs["minimum_id"]
        inclusive = kwargs["minimum_id_inclusive"]
        ids = rows_by_resource[entry.integration_resource_id]
        return [
            {
                "id": str(index),
                "name": f"List {index}",
                "memberCount": index,
            }
            for index in ids
            if minimum_id is None or index > minimum_id or (inclusive and index == minimum_id)
        ][: kwargs["limit"]]

    monkeypatch.setattr("integrations.google_ads.entity_resolvers.shared_set._query", query)

    pages = []
    cursors = []
    cursor = None
    while True:
        page = await search_google_ads_shared_sets(ctx, "Brand's \\ list", {}, 2, cursor)
        pages.append(page)
        if page.next_cursor is None:
            break
        assert page.next_cursor not in cursors
        cursors.append(page.next_cursor)
        cursor = page.next_cursor

    choices = [choice for page in pages for choice in page.choices]
    identities = [
        (choice.value["customer_id"], choice.value["shared_set_id"]) for choice in choices
    ]
    assert len(choices) == 10
    assert len(identities) == len(set(identities))
    expected = {
        (entity_id, entry.external_id)
        for entry in entries
        for entity_id in rows_by_resource[entry.integration_resource_id]
    }
    assert identities == [
        (customer_id, str(entity_id)) for entity_id, customer_id in sorted(expected)
    ]
    assert all(len(page.choices) <= 2 for page in pages)
    assert pages[-1].next_cursor is None
    assert all(kwargs["search"] == "Brand's \\ list" for _, kwargs in query_calls)
    assert all(kwargs["limit"] == 3 for _, kwargs in query_calls)

    replayed_page = await search_google_ads_shared_sets(ctx, "Brand's \\ list", {}, 2, cursors[1])
    assert replayed_page == pages[2]


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


async def test_shared_set_search_restarts_stale_cursor_and_propagates_provider_failure(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(entry,)),
    )
    query = AsyncMock(
        return_value=[
            {"id": "1", "name": "First", "memberCount": 1},
            {"id": "2", "name": "Second", "memberCount": 2},
        ]
    )
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.shared_set._query", query)
    first = await search_google_ads_shared_sets(ctx, "old", {}, 1, None)

    restarted = await search_google_ads_shared_sets(ctx, "new", {}, 1, first.next_cursor)

    assert restarted.choices[0].value["shared_set_id"] == "1"
    assert query.await_args.kwargs["minimum_id"] is None

    query.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await search_google_ads_shared_sets(ctx, "new", {}, 1, None)


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
                "customer_id": "111",
                "shared_set_id": "customers/111/sharedSets/50",
                "label": "Current list",
            },
            GoogleAdsSharedSetReference(
                customer_id="999",
                shared_set_id="60",
                label="Inactive list",
            ),
        ],
        {},
    )

    assert [choice.value["shared_set_id"] for choice in choices] == ["50"]
    assert query.await_args.kwargs["shared_set_ids"] == ["50"]
    assert query.await_args.kwargs["limit"] == 1


async def test_campaign_targeted_search_reaches_match_beyond_old_101_prefix(monkeypatch) -> None:
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
    campaigns = [
        {
            "id": str(index),
            "name": "Needle campaign" if index == 150 else f"Campaign {index}",
            "status": "ENABLED",
        }
        for index in range(1, 151)
    ]

    async def query(_ctx, _entry, **kwargs):
        minimum_id = kwargs["minimum_id"]
        normalized_search = (kwargs["search"] or "").casefold()
        return [
            campaign
            for campaign in campaigns
            if normalized_search in campaign["name"].casefold()
            and (minimum_id is None or int(campaign["id"]) > minimum_id)
        ][: kwargs["limit"]]

    monkeypatch.setattr("integrations.google_ads.entity_resolvers.campaign._query", query)

    page = await search_google_ads_campaigns(ctx, "Needle", {}, 25, None)

    assert [choice.value["campaign_id"] for choice in page.choices] == ["150", "150"]
    assert page.next_cursor is None


async def test_shared_set_targeted_search_reaches_match_beyond_provider_page_prefix(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(entry,)),
    )
    shared_sets = [
        {
            "id": str(index),
            "name": "Needle list" if index == 10_050 else f"List {index}",
            "memberCount": index,
        }
        for index in range(1, 10_051)
    ]

    async def query(_ctx, _entry, **kwargs):
        normalized_search = (kwargs["search"] or "").casefold()
        return [
            shared_set
            for shared_set in shared_sets
            if normalized_search in shared_set["name"].casefold()
        ][: kwargs["limit"]]

    monkeypatch.setattr("integrations.google_ads.entity_resolvers.shared_set._query", query)

    page = await search_google_ads_shared_sets(ctx, "Needle", {}, 25, None)

    assert [choice.value["shared_set_id"] for choice in page.choices] == ["10050"]
    assert page.next_cursor is None


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


async def test_ad_group_search_fans_out_and_labels_campaign_scope(monkeypatch) -> None:
    active = _writable_google_ads_entry()
    second_active = replace(
        active,
        integration_resource_id=uuid4(),
        external_id="222",
        connection_id=uuid4(),
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
            {
                "adGroup": {"id": "10", "name": "Exact", "status": "ENABLED"},
                "campaign": {"id": "1", "name": "Brand"},
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
            "minimum_id": None,
            "minimum_id_inclusive": False,
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
                "campaign": {"id": "1", "name": "Brand"},
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
        minimum_id=None,
        minimum_id_inclusive=False,
        limit=1,
        exclude_removed=True,
    )
    ad_group_operation.assert_awaited_once_with(
        client,
        customer_id="111",
        login_customer_id="999",
        ad_group_ids=["20"],
        search=None,
        minimum_id=None,
        minimum_id_inclusive=False,
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
