"""Google Ads label reference, lookup, and action contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from integrations.google_ads.entity_resolvers.label import resolve_google_ads_labels
from integrations.google_ads.operations.count_label_associations import (
    LABEL_ASSOCIATION_ROW_BOUND,
    count_label_associations,
)
from integrations.google_ads.operations.list_labels import list_labels
from integrations.google_ads.references import (
    GoogleAdsLabelAssociationCounts,
    GoogleAdsLabelReference,
)
from integrations.google_ads.tools.create_labels import google_ads_create_labels
from integrations.google_ads.tools.schemas import GoogleAdsCreateLabelsOutput, GoogleAdsLabelDraft
from integrations.google_ads.tools.verifiers import verify_labels
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
    assert counts["8"].ad == LABEL_ASSOCIATION_ROW_BOUND
    assert counts["7"].truncated and counts["8"].truncated
    keyword_query = next(query for query in client.queries if "ad_group_criterion_label" in query)
    assert "ad_group_criterion.negative = FALSE" in keyword_query


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
                "7": GoogleAdsLabelAssociationCounts(campaign=3, ad_group=0, keyword=12, ad=1)
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
        "ad": 1,
        "truncated": False,
    }
