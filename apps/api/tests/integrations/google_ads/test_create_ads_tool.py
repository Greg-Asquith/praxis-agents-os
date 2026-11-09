# apps/api/tests/integrations/google_ads/test_create_ads_tool.py

"""Creating responsive search ads: checks before approval, one atomic request, and read-back."""

import re
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.google_ads.references import GoogleAdsAdGroupReference
from integrations.google_ads.tools import create_ads as tool_module
from integrations.google_ads.tools.schemas.ads import GoogleAdsCreateAdsOutput
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_C = "customers/111"


class _Account:
    """One Google Ads account: answers ad group and ad reads and applies `googleAds:mutate`."""

    def __init__(
        self,
        *,
        channels: dict[str, str],
        rejected: dict[str, str] | None = None,
        removed_campaigns: frozenset[str] = frozenset(),
    ):
        self.channels = channels
        self.rejected = rejected or {}
        self.removed_campaigns = removed_campaigns
        self.mutates: list[dict[str, Any]] = []
        self.created: list[str] = []

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            return [{"results": self._rows(body["query"])}]
        self.mutates.append(body)
        responses, errors = [], []
        for index, operation in enumerate(body["mutateOperations"]):
            ad_group = operation["adGroupAdOperation"]["create"]["adGroup"]
            if ad_group in self.rejected:
                responses.append({})
                errors.append(_error(index, self.rejected[ad_group]))
                continue
            name = f"{_C}/adGroupAds/{ad_group.rsplit('/', 1)[1]}~{900 + index}"
            if not body["validateOnly"]:
                self.created.append(name)
            responses.append({"adGroupAdResult": {"resourceName": name}})
        reply: dict[str, Any] = {"mutateOperationResponses": responses}
        if errors:
            reply["partialFailureError"] = {"details": [{"errors": errors}]}
        return reply

    def _rows(self, query: str) -> list[dict[str, Any]]:
        if query.endswith(")") and "FROM ad_group_ad" in query:
            return [
                {
                    "adGroupAd": {
                        "resourceName": name,
                        "status": "PAUSED",
                        "policySummary": {"reviewStatus": "REVIEW_IN_PROGRESS"},
                    }
                }
                for name in re.findall(r"'([^']+)'", query)
                if name in self.created
            ]
        ids = re.search(r"ad_group\.id IN \(([^)]*)\)", query).group(1).split(", ")
        return [
            {
                "adGroup": {"id": ad_group_id, "name": f"Group {ad_group_id}", "status": "ENABLED"},
                "campaign": {"name": "Trail", "advertisingChannelType": self.channels[ad_group_id]},
            }
            for ad_group_id in ids
            if ad_group_id in self.channels
            and not (
                ad_group_id in self.removed_campaigns and "campaign.status != 'REMOVED'" in query
            )
        ]


def _error(index: int, topic: str) -> dict[str, Any]:
    return {
        "message": "The resource has been disapproved since the policy summary includes "
        "policy topics of type PROHIBITED.",
        "errorCode": {"policyFindingError": "POLICY_FINDING"},
        "details": {
            "policyFindingDetails": {"policyTopicEntries": [{"topic": topic, "type": "PROHIBITED"}]}
        },
        "location": {"fieldPathElements": [{"fieldName": "mutate_operations", "index": index}]},
    }


def _ad_group(ad_group_id: str, *, customer_id: str = "111") -> dict[str, Any]:
    return GoogleAdsAdGroupReference(
        customer_id=customer_id,
        campaign_id="10",
        ad_group_id=ad_group_id,
        label=f"Group {ad_group_id}",
    ).model_dump(mode="json")


def _ad(*ad_group_ids: str, headline: str = "Trail Shoes", customer_id: str = "111") -> dict:
    return {
        "headlines": [
            {"text": headline, "pin": "HEADLINE_1"},
            {"text": "Free Returns"},
            {"text": "Grip Any Trail"},
        ],
        "descriptions": [{"text": "Lightweight trail shoes."}, {"text": "Free UK delivery."}],
        "final_url": "https://example.com/trail",
        "path1": "trail",
        "path2": "sale",
        "ad_groups": [_ad_group(item, customer_id=customer_id) for item in ad_group_ids],
    }


def _entry():
    entry = _writable_google_ads_entry()
    metadata = {**entry.permissions_metadata, "currency_code": "GBP", "time_zone": "Europe/London"}
    return replace(entry, permissions_metadata=metadata)


async def _display(monkeypatch, account: _Account, args: dict[str, Any]) -> dict[str, Any]:
    monkeypatch.setattr(
        tool_module, "google_ads_client_for_principal", AsyncMock(return_value=account)
    )
    deps = SimpleNamespace(
        db=None,
        user=None,
        workspace=None,
        active_context=ResolvedActiveContext(entries=(_entry(),)),
    )
    return await tool_module._approval_display_args(deps, args)


async def _run(monkeypatch, account: _Account, args: dict[str, Any], display: dict[str, Any]):
    monkeypatch.setattr(tool_module, "google_ads_client", AsyncMock(return_value=account))
    monkeypatch.setattr(tool_module, "approved_display_args", lambda _ctx: display)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(_entry(),)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_create_ads",
        tool_call_id="create-ads-call",
    )
    request = tool_module.GoogleAdsCreateAdsRequest.model_validate(args)
    result = await tool_module.google_ads_create_ads(ctx, request.ads, request.status)
    return result, audit


async def test_one_atomic_request_creates_an_ad_in_two_ad_groups_and_reads_back_review(
    monkeypatch,
) -> None:
    account = _Account(channels={"20": "SEARCH", "21": "SEARCH"})
    args = {"ads": [_ad("20", "21")]}
    display = await _display(monkeypatch, account, args)

    result, audit = await _run(monkeypatch, account, args, display)

    sent = account.mutates[-1]
    assert sent["validateOnly"] is False and sent["partialFailure"] is False
    assert sent["mutateOperations"] == [
        {
            "adGroupAdOperation": {
                "create": {
                    "adGroup": f"{_C}/adGroups/{ad_group_id}",
                    "status": "PAUSED",
                    "ad": {
                        "finalUrls": ["https://example.com/trail"],
                        "responsiveSearchAd": {
                            "headlines": [
                                {"text": "Trail Shoes", "pinnedField": "HEADLINE_1"},
                                {"text": "Free Returns"},
                                {"text": "Grip Any Trail"},
                            ],
                            "descriptions": [
                                {"text": "Lightweight trail shoes."},
                                {"text": "Free UK delivery."},
                            ],
                            "path1": "trail",
                            "path2": "sale",
                        },
                    },
                }
            }
        }
        for ad_group_id in ("20", "21")
    ]
    rows = GoogleAdsCreateAdsOutput.model_validate(result).results[0].data.ads
    assert [(row.ad_group_name, row.outcome, row.status, row.review_status) for row in rows] == [
        ("Group 20", "created", "PAUSED", "REVIEW_IN_PROGRESS"),
        ("Group 21", "created", "PAUSED", "REVIEW_IN_PROGRESS"),
    ]
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


def test_a_headline_over_30_characters_is_refused_before_any_request() -> None:
    with pytest.raises(ModelRetry, match="at most 30 characters"):
        tool_module.validated_request(
            tool_module.GoogleAdsCreateAdsRequest,
            {"ads": [_ad("20", headline="Grip Any Trail. Free Returns Today")]},
        )


async def test_approval_flags_unusable_ad_groups_and_googles_rejection_per_ad(
    monkeypatch,
) -> None:
    account = _Account(
        channels={"20": "SEARCH", "21": "DISPLAY", "22": "SEARCH", "23": "SEARCH"},
        rejected={f"{_C}/adGroups/22": "DESTINATION_NOT_WORKING"},
        removed_campaigns=frozenset({"23"}),
    )
    args = {"ads": [_ad("20", "21", "23"), _ad("22", headline="Trail Runners")]}

    checks = (await _display(monkeypatch, account, args))["_checks"]

    dry_run = account.mutates[0]
    assert dry_run["validateOnly"] is True
    sent_groups = [
        operation["adGroupAdOperation"]["create"]["adGroup"]
        for operation in dry_run["mutateOperations"]
    ]
    assert sent_groups == [f"{_C}/adGroups/20", f"{_C}/adGroups/22"]
    assert checks["ad_groups"][f"{_C}/adGroups/21"]["problem"] == (
        "Responsive search ads only go in Search campaigns."
    )
    assert checks["ad_groups"][f"{_C}/adGroups/23"]["problem"] == (
        "This ad group or its campaign is removed, or no longer exists in Google Ads."
    )
    assert [ad["problems"] for ad in checks["ads"]] == [
        [],
        [
            {
                "ad_group": f"{_C}/adGroups/22",
                "message": "Google says: Disapproved under the Destination Not Working policy.",
            }
        ],
    ]


async def test_an_ad_group_in_an_account_outside_the_context_is_refused(monkeypatch) -> None:
    account = _Account(channels={"20": "SEARCH"})
    args = {"ads": [_ad("20", customer_id="222")]}

    with pytest.raises(ModelRetry, match="no longer in the active integration context"):
        await _run(monkeypatch, account, args, {"_checks": {}})

    assert account.mutates == []
