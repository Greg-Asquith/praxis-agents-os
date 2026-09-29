"""Google Ads label reference, lookup, and action contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.entity_resolvers.label import resolve_google_ads_labels
from integrations.google_ads.operations.count_label_associations import (
    LABEL_ASSOCIATION_ROW_BOUND,
    count_label_associations,
)
from integrations.google_ads.operations.list_labels import list_labels
from integrations.google_ads.operations.mutate_label_associations import (
    GoogleAdsLabelAssociation,
    mutate_label_associations,
)
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignReference,
    GoogleAdsKeywordReference,
    GoogleAdsLabelAssociationCounts,
    GoogleAdsLabelReference,
)
from integrations.google_ads.tools.apply_labels import google_ads_apply_labels
from integrations.google_ads.tools.create_labels import google_ads_create_labels
from integrations.google_ads.tools.delete_labels import google_ads_delete_labels
from integrations.google_ads.tools.remove_labels import google_ads_remove_labels
from integrations.google_ads.tools.schemas import (
    GoogleAdsApplyLabelsOutput,
    GoogleAdsCreateLabelsOutput,
    GoogleAdsDeleteLabelsOutput,
    GoogleAdsLabelDraft,
)
from integrations.google_ads.tools.schemas.labels import (
    GoogleAdsAdGroupLabelTarget,
    GoogleAdsCampaignLabelTarget,
    GoogleAdsKeywordLabelTarget,
)
from integrations.google_ads.tools.verifiers import verify_label_targets, verify_labels
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry


def _partial_failure(index: int, code: str) -> dict:
    return {
        "details": [
            {
                "errors": [
                    {
                        "message": "Rejected",
                        "errorCode": {"labelError": code},
                        "location": {
                            "fieldPathElements": [{"fieldName": "operations", "index": index}]
                        },
                    }
                ]
            }
        ]
    }


class _LabelClient:
    def __init__(self, *, search_payload, mutate_payload=None):
        self.search_payload = search_payload
        self.mutate_payload = mutate_payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            return self.search_payload
        if path.endswith("labels:mutate") and self.mutate_payload is not None:
            return self.mutate_payload
        raise AssertionError(f"Unexpected Google Ads operation path: {path}")


def _label_row(label_id: str, name: str, *, customer_id: str = "111") -> dict:
    return {
        "label": {
            "resourceName": f"customers/{customer_id}/labels/{label_id}",
            "id": label_id,
            "name": name,
            "status": "ENABLED",
            "textLabel": {"description": "Seasonal", "backgroundColor": "#1A73E8"},
        }
    }


def _create_ctx(entry):
    return SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name="google_ads_create_labels",
    )


def _patch_create(monkeypatch, client) -> list:
    audits: list = []

    async def capture_audit(_ctx, _entry, **kwargs):
        outcome = await kwargs["execute"]()
        audits.append(outcome)
        return outcome.value

    monkeypatch.setattr(
        "integrations.google_ads.tools.create_labels.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_labels.run_audited_integration_operation",
        capture_audit,
    )
    return audits


def test_label_draft_pins_google_name_description_and_colour_bounds() -> None:
    assert GoogleAdsLabelDraft(name=f"  {'a' * 40}   {'b' * 39} ").name == f"{'a' * 40} {'b' * 39}"
    assert GoogleAdsLabelDraft(name="Q4", background_color="#abc").background_color == "#abc"
    with pytest.raises(ValidationError):
        GoogleAdsLabelDraft(name="a" * 81)
    with pytest.raises(ValidationError):
        GoogleAdsLabelDraft(name="Q4", description="d" * 201)
    with pytest.raises(ValidationError):
        GoogleAdsLabelDraft(name="Q4", background_color="blue")


async def test_create_labels_skips_existing_names_and_keeps_colour_and_description(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry()
    client = _LabelClient(
        search_payload={"results": [_label_row("7", "Brand")]},
        mutate_payload={
            "results": [{"resourceName": "customers/111/labels/8"}, {}],
            "partialFailure": None,
            "partialFailureError": _partial_failure(1, "INVALID_BACKGROUND_COLOR"),
        },
    )
    audits = _patch_create(monkeypatch, client)

    result = await google_ads_create_labels(
        _create_ctx(entry),
        [
            GoogleAdsLabelDraft(name="brand", description="Sale", background_color="#D93025"),
            GoogleAdsLabelDraft(
                name="Black Friday", description="Sale", background_color="#E8710A"
            ),
            GoogleAdsLabelDraft(name="Evergreen"),
        ],
    )

    mutate = client.calls[-1]
    assert mutate["path"] == "customers/111/labels:mutate"
    assert mutate["json"] == {
        "operations": [
            {
                "create": {
                    "name": "Black Friday",
                    "textLabel": {"description": "Sale", "backgroundColor": "#E8710A"},
                }
            },
            {"create": {"name": "Evergreen"}},
        ],
        "partialFailure": True,
    }
    output = GoogleAdsCreateLabelsOutput.model_validate(result)
    rows = output.results[0].data.labels
    assert [(row.name, row.outcome) for row in rows] == [
        ("Brand", "already_exists"),
        ("Black Friday", "created"),
        ("Evergreen", "failed"),
    ]
    assert (rows[0].description, rows[0].background_color) == ("Seasonal", "#1A73E8")
    assert rows[0].reference.label_id == "7"
    created = rows[1].reference
    assert (created.label_id, created.label_description, created.background_color) == (
        "8",
        "Sale",
        "#E8710A",
    )
    assert rows[2].error_code == "INVALID_BACKGROUND_COLOR"
    detail = audits[0].operation_detail
    assert audits[0].status == AuditStatus.PARTIAL
    assert [item.fields for item in detail.intent_groups[0].items[:2]] == [
        {"name": "brand", "description": "Sale", "background_color": "#D93025"},
        {"name": "Black Friday", "description": "Sale", "background_color": "#E8710A"},
    ]
    assert [outcome.status for outcome in detail.outcome_groups[0].outcomes] == [
        "skipped",
        "applied",
        "failed",
    ]


async def test_create_labels_never_writes_when_every_name_exists(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    client = _LabelClient(search_payload={"results": [_label_row("7", "Brand")]})
    _patch_create(monkeypatch, client)

    result = await google_ads_create_labels(_create_ctx(entry), [GoogleAdsLabelDraft(name="Brand")])

    assert [call["path"] for call in client.calls] == ["customers/111/googleAds:searchStream"]
    assert result["results"][0]["data"]["labels"][0]["outcome"] == "already_exists"


async def test_create_labels_retains_every_row_when_a_label_is_unverified(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    client = _LabelClient(
        search_payload={"results": [_label_row("7", "Brand")]},
        mutate_payload={
            "results": [
                {"resourceName": "customers/111/labels/8"},
                {},
                {"resourceName": "customers/111/labels/9"},
            ],
            "partialFailureError": _partial_failure(2, "DUPLICATE_NAME"),
        },
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_create_labels",
        tool_call_id="create-labels-unverified-call",
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_labels.google_ads_client",
        AsyncMock(return_value=client),
    )
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )

    result = await google_ads_create_labels(
        ctx,
        [
            GoogleAdsLabelDraft(name="Brand"),
            GoogleAdsLabelDraft(name="Q4"),
            GoogleAdsLabelDraft(name="Q1"),
            GoogleAdsLabelDraft(name="Q2"),
        ],
    )

    item = GoogleAdsCreateLabelsOutput.model_validate(result).results[0]
    assert (item.status, item.error_code) == ("error", "unverified_mutation")
    assert [(row.name, row.outcome) for row in item.data.labels] == [
        ("Brand", "already_exists"),
        ("Q4", "created"),
        ("Q1", "unverified"),
        ("Q2", "unverified"),
    ]
    assert item.data.labels[3].error_code == "CONTRADICTORY_OPERATION"
    assert audit.await_args.kwargs["status"] == AuditStatus.UNVERIFIED


async def test_create_labels_rejects_duplicate_names_before_any_request(monkeypatch) -> None:
    client = _LabelClient(search_payload={"results": []})
    _patch_create(monkeypatch, client)

    with pytest.raises(ModelRetry, match="unique"):
        await google_ads_create_labels(
            _create_ctx(_writable_google_ads_entry()),
            [GoogleAdsLabelDraft(name="Q4"), GoogleAdsLabelDraft(name="q4")],
        )

    assert client.calls == []


async def test_list_labels_drops_labels_owned_by_another_customer() -> None:
    client = _LabelClient(
        search_payload={
            "results": [_label_row("7", "Mine"), _label_row("9", "Manager", customer_id="999")]
        }
    )

    labels = await list_labels(client, customer_id="111", login_customer_id="999", limit=10)

    assert [label["id"] for label in labels] == ["7"]


async def test_label_association_counts_group_by_label_and_mark_bound_truncation() -> None:
    class CountClient:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def post(self, _path, **kwargs):
            query = kwargs["json"]["query"]
            self.queries.append(query)
            if query.startswith("SELECT campaign_label"):
                rows = [{"campaignLabel": {"label": "customers/111/labels/7"}}] * 2 + [
                    {"campaignLabel": {"label": "customers/111/labels/8"}}
                ]
            elif query.startswith("SELECT ad_group_criterion_label"):
                rows = [
                    {
                        "adGroupCriterionLabel": {"label": "customers/111/labels/7"},
                        "adGroupCriterion": {"type": "KEYWORD", "negative": negative},
                    }
                    for negative in (False, True)
                ]
            elif query.startswith("SELECT ad_group_ad_label"):
                rows = [{"adGroupAdLabel": {"label": "customers/111/labels/8"}}] * (
                    LABEL_ASSOCIATION_ROW_BOUND + 1
                )
            else:
                rows = []
            return {"results": rows}

    client = CountClient()

    counts = await count_label_associations(
        client, customer_id="111", login_customer_id="999", label_ids=["8", "7"]
    )

    assert (counts["7"].campaign, counts["8"].campaign) == (2, 1)
    assert (counts["7"].keyword, counts["7"].other_criterion) == (1, 1)
    assert counts["8"].ad == LABEL_ASSOCIATION_ROW_BOUND
    assert counts["7"].truncated and counts["8"].truncated


async def test_verify_labels_fails_closed_for_removed_or_missing_labels(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.label.list_labels",
        AsyncMock(return_value=[_label_row("7", "Brand")["label"]]),
    )

    verified = await verify_labels(AsyncMock(), entry=entry, label_ids=["7"])
    with pytest.raises(ModelRetry, match="label is unavailable"):
        await verify_labels(AsyncMock(), entry=entry, label_ids=["7", "8"])

    assert verified["7"].background_color == "#1A73E8"


async def test_label_resolver_hydrates_live_details_with_association_counts(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(entry,)), db=None, actor=None, workspace=None
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.label.google_ads_client_for_principal",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.label.list_labels",
        AsyncMock(return_value=[_label_row("7", "Brand")["label"]]),
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.label.count_label_associations",
        AsyncMock(
            return_value={
                "7": GoogleAdsLabelAssociationCounts(
                    campaign=3, ad_group=0, keyword=12, other_criterion=2, ad=1
                )
            }
        ),
    )

    choices = await resolve_google_ads_labels(
        ctx,
        [GoogleAdsLabelReference(customer_id="111", label_id="7", label="Old name")],
        {},
    )

    assert choices[0].label == "Brand"
    assert choices[0].value["background_color"] == "#1A73E8"
    assert choices[0].value["association_counts"] == {
        "campaign": 3,
        "ad_group": 0,
        "keyword": 12,
        "other_criterion": 2,
        "ad": 1,
        "truncated": False,
    }


class _AssociationClient:
    """Answers association reads with `existing` and mutates with per-service payloads."""

    def __init__(self, *, existing=(), mutate_payloads=None):
        self.existing = existing
        self.mutate_payloads = mutate_payloads or {}
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            query = kwargs["json"]["query"]
            return {
                "results": [
                    {row_key: {"resourceName": name}}
                    for row_key, name in self.existing
                    if f"'{name}'" in query
                ]
            }
        service = path.rsplit("/", 1)[-1].removesuffix(":mutate")
        payload = self.mutate_payloads[service]
        if isinstance(payload, Exception):
            raise payload
        return payload


def _mutations(client) -> list[dict]:
    return [call for call in client.calls if call["path"].endswith(":mutate")]


def _label(label_id: str = "7", *, customer_id: str = "111") -> GoogleAdsLabelReference:
    return GoogleAdsLabelReference(customer_id=customer_id, label_id=label_id, label="Q4")


def _targets(customer_id: str = "111") -> list:
    return [
        GoogleAdsCampaignLabelTarget(
            kind="campaign",
            campaign=GoogleAdsCampaignReference(
                customer_id=customer_id, campaign_id="1", label="Brand"
            ),
        ),
        GoogleAdsAdGroupLabelTarget(
            kind="ad_group",
            ad_group=GoogleAdsAdGroupReference(
                customer_id=customer_id, campaign_id="1", ad_group_id="2", label="Shoes"
            ),
        ),
        GoogleAdsKeywordLabelTarget(
            kind="keyword",
            keyword=GoogleAdsKeywordReference(
                customer_id=customer_id,
                campaign_id="1",
                ad_group_id="2",
                criterion_id="3",
                text="red shoes",
                match_type="EXACT",
                status="ENABLED",
                label="red shoes",
            ),
        ),
    ]


async def test_apply_labels_builds_associations_per_service_and_skips_existing() -> None:
    client = _AssociationClient(
        existing=[("campaignLabel", "customers/111/campaignLabels/1~7")],
        mutate_payloads={
            "adGroupLabels": {"results": [{"resourceName": "customers/111/adGroupLabels/2~7"}]},
            "adGroupCriterionLabels": {
                "results": [{}],
                "partialFailureError": _partial_failure(0, "INVALID_LABEL"),
            },
        },
    )

    ledger = await mutate_label_associations(
        client,
        customer_id="111",
        login_customer_id="999",
        action="apply",
        associations=[
            GoogleAdsLabelAssociation("7", "campaign", "1"),
            GoogleAdsLabelAssociation("7", "ad_group", "2"),
            GoogleAdsLabelAssociation("7", "keyword", "2~3"),
        ],
    )

    assert [(call["path"], call["json"]["operations"]) for call in _mutations(client)] == [
        (
            "customers/111/adGroupLabels:mutate",
            [
                {
                    "create": {
                        "adGroup": "customers/111/adGroups/2",
                        "label": "customers/111/labels/7",
                    }
                }
            ],
        ),
        (
            "customers/111/adGroupCriterionLabels:mutate",
            [
                {
                    "create": {
                        "adGroupCriterion": "customers/111/adGroupCriteria/2~3",
                        "label": "customers/111/labels/7",
                    }
                }
            ],
        ),
    ]
    assert ledger.result()["already_applied"] == [
        {"label_id": "7", "target_kind": "campaign", "target_id": "1"}
    ]
    assert ledger.result()["applied"][0]["resource_name"] == "customers/111/adGroupLabels/2~7"
    assert ledger.result()["association_errors"][0]["error_code"] == "INVALID_LABEL"


async def test_remove_labels_skips_absent_pairs_and_records_a_later_service_failure() -> None:
    client = _AssociationClient(
        existing=[
            ("campaignLabel", "customers/111/campaignLabels/1~7"),
            ("adGroupLabel", "customers/111/adGroupLabels/2~7"),
        ],
        mutate_payloads={
            "campaignLabels": {"results": [{"resourceName": "customers/111/campaignLabels/1~7"}]},
            "adGroupLabels": IntegrationError(
                "Timed out", failure_disposition=IntegrationFailureDisposition.AMBIGUOUS
            ),
        },
    )

    ledger = await mutate_label_associations(
        client,
        customer_id="111",
        login_customer_id="999",
        action="remove",
        associations=[
            GoogleAdsLabelAssociation("7", "campaign", "1"),
            GoogleAdsLabelAssociation("7", "ad_group", "2"),
            GoogleAdsLabelAssociation("7", "keyword", "2~3"),
        ],
    )

    assert _mutations(client)[0]["json"]["operations"] == [
        {"remove": "customers/111/campaignLabels/1~7"}
    ]
    assert not any("labels:mutate" in call["path"] for call in client.calls)
    assert [effect.outcome for effect in ledger.effects] == ["applied", "unverified"]
    assert ledger.result()["not_applied"] == [
        {"label_id": "7", "target_kind": "keyword", "target_id": "2~3"}
    ]


async def test_label_changes_reject_cross_account_pairs_and_oversized_products(
    monkeypatch,
) -> None:
    client = _AssociationClient()
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.label_associations.google_ads_client",
        AsyncMock(return_value=client),
    )
    ctx = _create_ctx(_writable_google_ads_entry())

    with pytest.raises(ModelRetry, match="same account"):
        await google_ads_apply_labels(ctx, [_label(customer_id="222")], _targets())
    campaigns = [
        GoogleAdsCampaignLabelTarget(
            kind="campaign",
            campaign=GoogleAdsCampaignReference(
                customer_id="111", campaign_id=str(index), label=f"C{index}"
            ),
        )
        for index in range(1, 252)
    ]
    with pytest.raises(ModelRetry, match="at most 500"):
        await google_ads_remove_labels(ctx, [_label("7"), _label("8")], campaigns)

    assert client.calls == []


async def test_apply_labels_tool_reports_each_pair_and_audits_by_label(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    client = _AssociationClient(
        existing=[("adGroupLabel", "customers/111/adGroupLabels/2~7")],
        mutate_payloads={
            "campaignLabels": {"results": [{"resourceName": "customers/111/campaignLabels/1~7"}]},
            "adGroupCriterionLabels": {
                "results": [{"resourceName": "customers/111/adGroupCriterionLabels/2~3~7"}]
            },
        },
    )
    audits: list = []

    async def capture_audit(_ctx, _entry, **kwargs):
        await kwargs["prepare_pending_operation"]()
        outcome = await kwargs["execute"]()
        audits.append(outcome)
        return outcome.value

    module = "integrations.google_ads.tools.utils.label_associations"
    monkeypatch.setattr(f"{module}.google_ads_client", AsyncMock(return_value=client))
    monkeypatch.setattr(f"{module}.run_audited_integration_operation", capture_audit)
    live_label = _label().model_copy(update={"label": "Q4 live", "background_color": "#abc"})
    monkeypatch.setattr(f"{module}.verify_labels", AsyncMock(return_value={"7": live_label}))
    verify_targets = AsyncMock()
    monkeypatch.setattr(f"{module}.verify_label_targets", verify_targets)

    result = await google_ads_apply_labels(_create_ctx(entry), [_label()], _targets())

    rows = GoogleAdsApplyLabelsOutput.model_validate(result).results[0].data.associations
    assert [(row.target_kind, row.target_id, row.outcome) for row in rows] == [
        ("campaign", "1", "applied"),
        ("ad_group", "2", "already_applied"),
        ("keyword", "2~3", "applied"),
    ]
    assert (rows[0].label_name, rows[0].label_color) == ("Q4 live", "#abc")
    assert [ref.ad_group_id for ref in verify_targets.await_args.kwargs["ad_groups"]] == ["2"]
    detail = audits[0].operation_detail
    assert audits[0].status == AuditStatus.SUCCESS
    assert (detail.intent_groups[0].external_id, detail.intent_groups[0].fields) == (
        "7",
        {"label_id": "7"},
    )
    assert [outcome.status for outcome in detail.outcome_groups[0].outcomes] == [
        "applied",
        "skipped",
        "applied",
    ]


async def test_verify_label_targets_rejects_removed_ad_groups(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.label.list_ad_groups",
        AsyncMock(return_value=[{"adGroup": {"id": "2", "status": "REMOVED"}}]),
    )
    ad_group = _targets()[1].ad_group

    with pytest.raises(ModelRetry, match="unavailable"):
        await verify_label_targets(
            AsyncMock(), entry=entry, campaigns=[], ad_groups=[ad_group], keywords=[]
        )


async def test_delete_labels_records_rechecked_counts_and_partial_failure(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    client = _LabelClient(
        search_payload=None,
        mutate_payload={
            "results": [{"resourceName": "customers/111/labels/7"}, {}],
            "partialFailureError": _partial_failure(1, "CANNOT_REMOVE_LABEL"),
        },
    )
    audits: list = []

    async def capture_audit(_ctx, _entry, **kwargs):
        await kwargs["prepare_pending_operation"]()
        outcome = await kwargs["execute"]()
        audits.append(outcome)
        return outcome.value

    monkeypatch.setattr(
        "integrations.google_ads.tools.delete_labels.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.delete_labels.run_audited_integration_operation",
        capture_audit,
    )
    verifier = "integrations.google_ads.tools.verifiers.label"
    monkeypatch.setattr(
        f"{verifier}.list_labels",
        AsyncMock(return_value=[_label_row("7", "Q4")["label"], _label_row("8", "Q1")["label"]]),
    )
    live_counts = GoogleAdsLabelAssociationCounts(
        campaign=2, ad_group=0, keyword=5, other_criterion=1, ad=0
    )
    empty_counts = GoogleAdsLabelAssociationCounts(
        campaign=0, ad_group=0, keyword=0, other_criterion=0, ad=0
    )
    monkeypatch.setattr(
        f"{verifier}.count_label_associations",
        AsyncMock(return_value={"7": live_counts, "8": empty_counts}),
    )
    # The model-supplied counts are stale; the tool must record the re-read ones.
    stale = _label("7").model_copy(update={"association_counts": empty_counts})

    result = await google_ads_delete_labels(_create_ctx(entry), [stale, _label("8")])

    assert client.calls[-1]["json"] == {
        "operations": [
            {"remove": "customers/111/labels/7"},
            {"remove": "customers/111/labels/8"},
        ],
        "partialFailure": True,
    }
    rows = GoogleAdsDeleteLabelsOutput.model_validate(result).results[0].data.labels
    assert [(row.label_name, row.outcome) for row in rows] == [("Q4", "deleted"), ("Q1", "failed")]
    assert rows[0].association_counts == live_counts
    assert rows[1].error_code == "CANNOT_REMOVE_LABEL"
    assert audits[0].status == AuditStatus.PARTIAL
    intent = audits[0].operation_detail.intent_groups[0].items[0].fields
    assert intent["association_counts"]["keyword"] == 5
    assert audits[0].external_ref == "customers/111/labels/7"


async def test_delete_labels_fails_before_mutation_for_a_removed_label(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    client = _LabelClient(search_payload=None, mutate_payload={"results": []})

    async def capture_audit(_ctx, _entry, **kwargs):
        await kwargs["prepare_pending_operation"]()
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.delete_labels.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.delete_labels.run_audited_integration_operation",
        capture_audit,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.label.list_labels", AsyncMock(return_value=[])
    )

    result = await google_ads_delete_labels(_create_ctx(entry), [_label("7")])

    assert result["results"][0]["error_code"] == "ModelRetry"
    assert client.calls == []
