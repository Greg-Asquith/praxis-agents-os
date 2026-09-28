"""Positive-keyword removal approval, provider, and audit contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.google_ads.operations.remove_positive_keywords import (
    remove_positive_keywords,
)
from integrations.google_ads.tools.remove_positive_keywords import (
    DEFINITION,
    _pending_operation_detail,
    _preflight_call,
    _split_result,
    _validate_args,
    google_ads_remove_keywords,
)
from integrations.google_ads.tools.schemas.positive_keyword_removals import (
    GoogleAdsRemovePositiveKeywordsOutput,
)
from integrations.google_ads.tools.utils.mutation_evidence import terminal_operation_detail
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.google_ads.test_positive_keyword_update_tool import (
    SequencedClient,
    entry,
    keyword,
    provider_row,
)

MODULE = "integrations.google_ads.tools.remove_positive_keywords"


def context(selected=None):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(selected or entry(),)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="remove-keywords",
    )


async def test_remove_two_ad_groups_with_partial_failure():
    client = SequencedClient(
        [
            {
                "results": [{"resourceName": "customers/333/adGroupCriteria/20~90"}, {}],
                "partialFailureError": {
                    "details": [
                        {
                            "errors": [
                                {
                                    "errorCode": {"criterionError": "INVALID_KEYWORD_TEXT"},
                                    "message": "Removal rejected",
                                    "location": {
                                        "fieldPathElements": [
                                            {"fieldName": "operations", "index": 1},
                                        ]
                                    },
                                }
                            ]
                        }
                    ]
                },
            }
        ]
    )
    ledger = await remove_positive_keywords(
        client, customer_id="333", login_customer_id="111", keyword_ids=[("20", "90"), ("21", "90")]
    )
    path, request = client.calls[0]
    assert path == "customers/333/adGroupCriteria:mutate"
    assert request["policy"] is IntegrationRequestPolicy.MUTATION
    assert request["json"] == {
        "operations": [
            {"remove": "customers/333/adGroupCriteria/20~90"},
            {"remove": "customers/333/adGroupCriteria/21~90"},
        ],
        "partialFailure": True,
    }
    references = [keyword(), keyword().model_copy(update={"ad_group_id": "21"})]
    result = _split_result(references, ledger)["display_result"]
    assert result["counts"] == {"removed": 1, "failed": 1, "unverified": 0}
    assert result["samples"]["removed"][0]["resulting_status"] == "REMOVED"
    assert result["samples"]["failed"][0]["resulting_status"] == "PAUSED"
    detail = terminal_operation_detail(_pending_operation_detail(entry(), references), ledger)
    assert detail.intent_counts.applied == detail.intent_counts.failed == 1
    assert detail.intent_groups[0].items[1].fields["before"]["ad_group_id"] == "21"


@pytest.mark.parametrize(
    "change",
    [
        {"status": "ENABLED"},
        {"finalUrls": ["https://example.com/changed"]},
    ],
)
async def test_changed_keyword_fails_before_mutation(monkeypatch, change):
    row = provider_row()
    row["adGroupCriterion"].update(change)
    client = SequencedClient([[{"results": [row]}]])
    monkeypatch.setattr(f"{MODULE}.google_ads_client", AsyncMock(return_value=client))
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )
    result = await google_ads_remove_keywords(context(), [keyword()])
    assert len(client.calls) == 1
    assert result.return_value["results"][0]["status"] == "error"


@pytest.mark.parametrize("failure", [False, True])
async def test_tool_retains_pending_and_terminal_audit(monkeypatch, failure):
    second = provider_row("91")
    second["adGroup"]["id"] = "21"
    second["adGroupCriterion"]["resourceName"] = "customers/333/adGroupCriteria/21~91"
    client = SequencedClient(
        [
            [{"results": [provider_row(), second]}],
            RuntimeError("timeout")
            if failure
            else {
                "results": [
                    {"resourceName": "customers/333/adGroupCriteria/20~90"},
                    {"resourceName": "customers/333/adGroupCriteria/21~91"},
                ]
            },
        ]
    )
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(f"{MODULE}.google_ads_client", AsyncMock(return_value=client))
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    result = await google_ads_remove_keywords(
        context(), [keyword(), keyword("91").model_copy(update={"ad_group_id": "21"})]
    )
    output = GoogleAdsRemovePositiveKeywordsOutput.model_validate(result.metadata["public_result"])
    assert output.results[0].data is not None
    counts = output.results[0].data.counts
    assert counts.unverified == (2 if failure else 0)
    assert counts.removed == (0 if failure else 2)
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.UNVERIFIED if failure else AuditStatus.SUCCESS,
    ]
    terminal = audit.await_args_list[1].kwargs["operation_detail"]
    assert len(terminal.outcome_groups[0].outcomes) == 2
    assert terminal.intent_groups[0].items[0].fields["requested"] == "REMOVED"


def test_scope_and_large_evidence_fail_before_dispatch():
    with pytest.raises(ModelRetry, match="active Google Ads accounts"):
        _preflight_call(context().deps, [keyword().model_copy(update={"customer_id": "444"})])
    with pytest.raises(ModelRetry, match="too large"):
        _validate_args(
            None,
            [
                keyword(str(i)).model_copy(
                    update={"final_urls": ["https://example.com/" + "a" * 2000] * 10}
                )
                for i in range(50)
            ],
        )


@pytest.mark.parametrize(
    "change",
    [{"finalUrls": ["https://example.com/changed"]}],
)
async def test_approval_hydration_does_not_replace_stale_keyword_evidence(monkeypatch, change):
    from integrations.google_ads.entity_resolvers.keyword import resolve_google_ads_keywords

    row = provider_row()
    row["adGroupCriterion"].update(change)
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.keyword._query", AsyncMock(return_value=[row])
    )
    choices = await resolve_google_ads_keywords(context().deps, [keyword()], {})
    assert choices == ()
