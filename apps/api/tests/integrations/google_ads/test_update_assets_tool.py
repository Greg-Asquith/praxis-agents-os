# apps/api/tests/integrations/google_ads/test_update_assets_tool.py

"""Sitelinks and callouts on campaigns and ad groups: checked before approval, then sent."""

import re
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from integrations.google_ads.operations import assets as assets_operations
from integrations.google_ads.tools import update_assets as tool_module
from integrations.google_ads.tools.schemas.assets import (
    GoogleAdsUpdateAssetsOutput,
    GoogleAdsUpdateAssetsRequest,
)
from integrations.google_ads.tools.utils import edit_runs
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_C = "customers/111"


class _Account:
    """One Google Ads account's campaigns, ad groups, assets, and their links."""

    def __init__(self) -> None:
        self.campaigns = {"10": "Trail", "20": "Road"}
        self.ad_groups = {"40": ("Trail Shoes", "Trail")}
        self.assets: dict[str, dict[str, Any]] = {
            "70": {
                "type": "SITELINK",
                "source": "ADVERTISER",
                "finalUrls": ["https://shop.example/sale"],
                "sitelinkAsset": {"linkText": "Sale"},
            },
            "71": {
                "type": "CALLOUT",
                "source": "ADVERTISER",
                "calloutAsset": {"calloutText": "Free Returns"},
            },
            "72": {
                "type": "CALLOUT",
                "source": "ADVERTISER",
                "calloutAsset": {"calloutText": "Next-Day Delivery"},
            },
            "73": {
                "type": "CALLOUT",
                "source": "AUTOMATICALLY_CREATED",
                "calloutAsset": {"calloutText": "Made By Google"},
            },
        }
        # (collection, owner ID, asset ID, field type).
        self.links: set[tuple[str, str, str, str]] = {
            ("campaigns", "10", "70", "SITELINK"),
            ("campaigns", "20", "70", "SITELINK"),
            ("campaigns", "10", "71", "CALLOUT"),
            ("adGroups", "40", "72", "CALLOUT"),
        }
        # Assets linked to the whole account.
        self.account_assets: set[str] = set()
        # A new callout with this text is rejected by Google.
        self.rejected_callout: str | None = None
        self.mutates: list[dict[str, Any]] = []
        self.next_id = 900

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            return [{"results": self._search(body["query"])}]
        assert path == f"{_C}/googleAds:mutate"
        self.mutates.append(body)
        return self._mutate(body)

    def _asset(self, asset_id: str) -> dict[str, Any]:
        return {"id": asset_id, **self.assets[asset_id]}

    def _search(self, query: str) -> list[dict[str, Any]]:
        match = re.search(r"\.id IN \(([^)]*)\)", query)
        ids = set(re.findall(r"\d+", match.group(1))) if match else set()
        resource = re.search(r"FROM (\w+)", query).group(1)
        if resource == "campaign":
            return [
                {"campaign": {"id": key, "name": name, "status": "ENABLED"}}
                for key, name in self.campaigns.items()
                if key in ids
            ]
        if resource == "ad_group":
            return [
                {
                    "adGroup": {"id": key, "name": name, "status": "ENABLED"},
                    "campaign": {"name": campaign},
                }
                for key, (name, campaign) in self.ad_groups.items()
                if key in ids
            ]
        if resource == "asset":
            return [{"asset": self._asset(key)} for key in self.assets if key in ids]
        if resource == "customer_asset":
            return [{"asset": {"id": key}} for key in sorted(self.account_assets & ids)]
        collection, owner_key, names = {
            "campaign_asset": ("campaigns", "campaign", self.campaigns),
            "ad_group_asset": ("adGroups", "adGroup", {k: v[0] for k, v in self.ad_groups.items()}),
        }[resource]
        by_asset = query.startswith("SELECT asset.id,")
        return [
            {
                f"{owner_key}Asset": {
                    "resourceName": f"{_C}/{collection}Assets/{owner}~{asset}~{field}".replace(
                        "campaignsAssets", "campaignAssets"
                    ).replace("adGroupsAssets", "adGroupAssets")
                },
                owner_key: {"id": owner, "name": names[owner]},
                "asset": self._asset(asset),
            }
            for kind, owner, asset, field in sorted(self.links)
            if kind == collection and (asset if by_asset else owner) in ids
        ]

    def _mutate(self, body: dict[str, Any]) -> dict[str, Any]:
        created: dict[str, str] = {}
        responses: list[dict[str, Any]] = []
        errors = []
        for index, operation in enumerate(body["mutateOperations"]):
            ((key, value),) = operation.items()
            callout = value.get("create", {}).get("calloutAsset", {}).get("calloutText")
            if callout is not None and callout == self.rejected_callout:
                responses.append({})
                errors.append(
                    {
                        "message": "This text breaks a policy.",
                        "errorCode": {"policyFindingError": "POLICY_FINDING"},
                        "location": {
                            "fieldPathElements": [
                                {"fieldName": "mutate_operations", "index": index}
                            ]
                        },
                    }
                )
                continue
            name = self._apply(key.removesuffix("Operation"), value, created, body["validateOnly"])
            responses.append({key.replace("Operation", "Result"): {"resourceName": name}})
        reply: dict[str, Any] = {"mutateOperationResponses": responses}
        if errors:
            reply["partialFailureError"] = {"details": [{"errors": errors}]}
        return reply

    def _apply(self, resource: str, value: dict, created: dict, dry: bool) -> str:
        if "remove" in value:
            _c, _id, collection, ids = value["remove"].split("/")
            owner, asset, field = ids.split("~")
            if not dry:
                self.links.discard((collection.removesuffix("Assets") + "s", owner, asset, field))
            return value["remove"]
        if "update" in value:
            update = value["update"]
            asset_id = update["resourceName"].rsplit("/", 1)[1]
            if not dry:
                for path in value["updateMask"].split(","):
                    *parents, leaf = path.split(".")
                    source, target = update, self.assets[asset_id]
                    for part in parents:
                        source, target = source.get(part, {}), target.setdefault(part, {})
                    target[leaf] = source.get(leaf)
            return update["resourceName"]
        create = {
            key: created.get(item, item) if isinstance(item, str) else item
            for key, item in value["create"].items()
        }
        self.next_id += 1
        if resource == "asset":
            name = f"{_C}/assets/{self.next_id}"
            created[create.pop("resourceName")] = name
            if not dry:
                asset_type = "SITELINK" if "sitelinkAsset" in create else "CALLOUT"
                self.assets[str(self.next_id)] = {
                    "type": asset_type,
                    "source": "ADVERTISER",
                    **create,
                }
            return name
        owner_field, collection = {
            "campaignAsset": ("campaign", "campaigns"),
            "adGroupAsset": ("adGroup", "adGroups"),
        }[resource]
        owner = create[owner_field].rsplit("/", 1)[1]
        asset = create["asset"].rsplit("/", 1)[1]
        if not dry:
            self.links.add((collection, owner, asset, create["fieldType"]))
        return f"{_C}/{resource}s/{owner}~{asset}~{create['fieldType']}"


def _campaign(campaign_id: str) -> dict[str, Any]:
    return {"customer_id": "111", "campaign_id": campaign_id, "label": f"Campaign {campaign_id}"}


def _ad_group(ad_group_id: str) -> dict[str, Any]:
    return {**_campaign("10"), "ad_group_id": ad_group_id, "label": "Trail Shoes"}


def _asset(asset_id: str, asset_type: str = "CALLOUT") -> dict[str, Any]:
    return {"customer_id": "111", "asset_id": asset_id, "asset_type": asset_type, "label": "Asset"}


_NEW_SITELINK = {
    "type": "sitelink",
    "link_text": "Size Guide",
    "description1": "Find your size",
    "description2": "Fit tips for wide feet",
    "final_url": "https://shop.example/size-guide",
}
_FREE_RETURNS = {"type": "callout", "text": "Free Returns"}


def _args(entries: list[dict[str, Any]], change: list[dict[str, Any]] = ()) -> dict[str, Any]:
    return GoogleAdsUpdateAssetsRequest.model_validate(
        {"entries": entries, "change": list(change)}
    ).model_dump(mode="json")


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
    monkeypatch.setattr(edit_runs, "google_ads_client", AsyncMock(return_value=account))
    monkeypatch.setattr(tool_module, "approved_display_args", lambda _ctx: display)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(_entry(),)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_update_assets",
        tool_call_id="update-assets-call",
    )
    request = GoogleAdsUpdateAssetsRequest.model_validate(args)
    result = await tool_module.google_ads_update_assets(ctx, request.entries, request.change)
    GoogleAdsUpdateAssetsOutput.model_validate(result.return_value)
    shown = result.metadata["public_result"]
    return GoogleAdsUpdateAssetsOutput.model_validate(shown).model_dump(mode="json")


def _outcomes(result: dict[str, Any]) -> set[tuple[Any, ...]]:
    return {
        (row["target_name"], row["action"], row["asset_label"], row["outcome"])
        for row in result["results"][0]["data"]["outcomes"]
    }


async def test_one_approval_adds_new_assets_once_links_removes_and_edits_where_used(
    monkeypatch,
) -> None:
    account = _Account()
    account.account_assets = {"70"}
    args = _args(
        [
            {
                "kind": "campaign",
                "campaign": _campaign("10"),
                "add": [_NEW_SITELINK, _FREE_RETURNS],
            },
            {
                "kind": "campaign",
                "campaign": _campaign("20"),
                "add": [_NEW_SITELINK, _FREE_RETURNS],
            },
            {
                "kind": "ad_group",
                "ad_group": _ad_group("40"),
                "add": [{"type": "existing", "asset": _asset("71")}],
                # The reference's type is wrong; the card and result take the live asset's.
                "remove": [_asset("72", "SITELINK")],
            },
        ],
        [
            {
                "asset": _asset("70", "SITELINK"),
                "content": {
                    "type": "sitelink",
                    "link_text": "Winter Sale",
                    "final_url": "https://shop.example/sale",
                },
            }
        ],
    )

    display = await _display(monkeypatch, account, args)
    trail = display["_checks"][f"{_C}/campaigns/10"]
    # Campaign 10 already shows "Free Returns", so only the sitelink is new there.
    assert {(row["label"], row["state"]) for row in trail["rows"]} == {
        ("Size Guide", "change"),
        ("Free Returns", "already_set"),
    }
    assert trail["now"] == {"SITELINK": 1, "CALLOUT": 1}
    edited = display["_changes"][f"{_C}/assets/70"]
    assert (edited["used_in"], edited["account_level"]) == (["Trail", "Road"], True)
    removal = display["_checks"][f"{_C}/adGroups/40"]["rows"][0]
    assert (removal["action"], removal["asset_type"]) == ("remove", "CALLOUT")
    assert [body["validateOnly"] for body in account.mutates] == [True, True]

    result = await _run(monkeypatch, account, args, display)

    edits, build = account.mutates[2:]
    assert edits["partialFailure"] is True
    assert edits["mutateOperations"] == [
        {"adGroupAssetOperation": {"remove": f"{_C}/adGroupAssets/40~72~CALLOUT"}},
        {
            "adGroupAssetOperation": {
                "create": {
                    "adGroup": f"{_C}/adGroups/40",
                    "asset": f"{_C}/assets/71",
                    "fieldType": "CALLOUT",
                }
            }
        },
        {
            "assetOperation": {
                "update": {
                    "resourceName": f"{_C}/assets/70",
                    "sitelinkAsset": {"linkText": "Winter Sale"},
                },
                "updateMask": "sitelinkAsset.linkText",
            }
        },
    ]
    # Each new asset is made once and linked to every campaign in one atomic request.
    assert build["partialFailure"] is False
    assert build["mutateOperations"] == [
        {
            "assetOperation": {
                "create": {
                    "sitelinkAsset": {
                        "linkText": "Size Guide",
                        "description1": "Find your size",
                        "description2": "Fit tips for wide feet",
                    },
                    "finalUrls": ["https://shop.example/size-guide"],
                    "resourceName": f"{_C}/assets/-1",
                }
            }
        },
        {
            "assetOperation": {
                "create": {
                    "calloutAsset": {"calloutText": "Free Returns"},
                    "resourceName": f"{_C}/assets/-2",
                }
            }
        },
        {
            "campaignAssetOperation": {
                "create": {
                    "campaign": f"{_C}/campaigns/10",
                    "asset": f"{_C}/assets/-1",
                    "fieldType": "SITELINK",
                }
            }
        },
        {
            "campaignAssetOperation": {
                "create": {
                    "campaign": f"{_C}/campaigns/20",
                    "asset": f"{_C}/assets/-1",
                    "fieldType": "SITELINK",
                }
            }
        },
        {
            "campaignAssetOperation": {
                "create": {
                    "campaign": f"{_C}/campaigns/20",
                    "asset": f"{_C}/assets/-2",
                    "fieldType": "CALLOUT",
                }
            }
        },
    ]
    assert _outcomes(result) == {
        ("Trail", "add", "Size Guide", "added"),
        ("Trail", "add", "Free Returns", "already_set"),
        ("Road", "add", "Size Guide", "added"),
        ("Road", "add", "Free Returns", "added"),
        ("Trail Shoes", "add", "Free Returns", "added"),
        ("Trail Shoes", "remove", "Next-Day Delivery", "removed"),
        (None, "change", "Winter Sale", "changed"),
    }


async def test_an_asset_google_made_is_refused_and_nothing_is_sent_for_it(monkeypatch) -> None:
    account = _Account()
    args = _args(
        [
            {
                "kind": "campaign",
                "campaign": _campaign("20"),
                "add": [{"type": "existing", "asset": _asset("73")}],
            }
        ],
        [{"asset": _asset("73"), "content": {"type": "callout", "text": "Mine Now"}}],
    )

    display = await _display(monkeypatch, account, args)
    assert (
        display["_checks"][f"{_C}/campaigns/20"]["rows"][0]["problem"]
        == tool_module._MADE_BY_GOOGLE
    )
    assert display["_changes"][f"{_C}/assets/73"]["problem"] == tool_module._MADE_BY_GOOGLE

    result = await _run(monkeypatch, account, args, display)

    assert all(body["validateOnly"] for body in account.mutates)
    assert {row[3] for row in _outcomes(result)} == {"failed"}


async def test_an_asset_edited_in_google_ads_after_approval_is_not_overwritten(
    monkeypatch,
) -> None:
    account = _Account()
    args = _args(
        [],
        [{"asset": _asset("71"), "content": {"type": "callout", "text": "Free 60-Day Returns"}}],
    )
    display = await _display(monkeypatch, account, args)
    account.assets["71"]["calloutAsset"]["calloutText"] = "Free Returns Always"

    result = await _run(monkeypatch, account, args, display)

    assert all(body["validateOnly"] for body in account.mutates)
    (row,) = result["results"][0]["data"]["outcomes"]
    assert (row["outcome"], row["error_code"]) == ("failed", "CHANGED_SINCE_APPROVAL")
    assert account.assets["71"]["calloutAsset"]["calloutText"] == "Free Returns Always"


def test_a_target_cannot_use_an_asset_from_another_account() -> None:
    foreign = {**_asset("71"), "customer_id": "222"}
    with pytest.raises(ValidationError, match="its own account"):
        _args([{"kind": "campaign", "campaign": _campaign("10"), "remove": [foreign]}])


async def test_many_links_with_long_urls_fit_the_audit_record(monkeypatch) -> None:
    account = _Account()
    account.campaigns = {str(100 + index): f"Campaign {index}" for index in range(50)}
    sitelinks = [
        {
            "type": "sitelink",
            "link_text": f"Page {index}",
            "final_url": f"https://shop.example/{'p' * 2000}/{index}",
        }
        for index in range(20)
    ]
    args = _args(
        [
            {"kind": "campaign", "campaign": _campaign(campaign_id), "add": sitelinks}
            for campaign_id in account.campaigns
        ]
    )

    display = await _display(monkeypatch, account, args)
    result = await _run(monkeypatch, account, args, display)

    assert result["results"][0]["data"]["counts"]["added"] == 1000


async def test_assets_used_in_more_places_than_one_read_holds_are_not_shown_with_a_low_count(
    monkeypatch,
) -> None:
    monkeypatch.setattr(assets_operations, "_MAX_USES", 2)
    args = _args(
        [],
        [
            {
                "asset": _asset("70", "SITELINK"),
                "content": {
                    "type": "sitelink",
                    "link_text": "Winter Sale",
                    "final_url": "https://shop.example/sale",
                },
            }
        ],
    )

    with pytest.raises(ModelRetry):
        await _display(monkeypatch, _Account(), args)


async def test_additions_that_would_pass_twenty_of_a_type_are_refused_after_counting_removals(
    monkeypatch,
) -> None:
    account = _Account()
    for index in range(20):
        account.assets[str(200 + index)] = {
            "type": "CALLOUT",
            "source": "ADVERTISER",
            "calloutAsset": {"calloutText": f"Perk {index}"},
        }
        account.links.add(("campaigns", "20", str(200 + index), "CALLOUT"))
    swap = {
        "kind": "campaign",
        "campaign": _campaign("20"),
        "add": [{"type": "callout", "text": "New Perk"}],
        "remove": [_asset("200")],
    }

    display = await _display(monkeypatch, account, _args([swap]))
    assert [row["problem"] for row in display["_checks"][f"{_C}/campaigns/20"]["rows"]] == [
        None,
        None,
    ]

    over = {**swap, "add": [*swap["add"], {"type": "callout", "text": "Second Perk"}]}
    args = _args([over])
    display = await _display(monkeypatch, account, args)
    rows = display["_checks"][f"{_C}/campaigns/20"]["rows"]
    assert [(row["action"], row["problem"] is None) for row in rows] == [
        ("remove", True),
        ("add", False),
        ("add", False),
    ]

    result = await _run(monkeypatch, account, args, display)

    assert _outcomes(result) == {
        ("Road", "remove", "Perk 0", "removed"),
        ("Road", "add", "New Perk", "failed"),
        ("Road", "add", "Second Perk", "failed"),
    }


async def test_a_new_asset_matching_one_being_removed_is_created_rather_than_left_out(
    monkeypatch,
) -> None:
    account = _Account()
    args = _args(
        [
            {
                "kind": "campaign",
                "campaign": _campaign("10"),
                "add": [_FREE_RETURNS],
                "remove": [_asset("71")],
            }
        ]
    )

    display = await _display(monkeypatch, account, args)
    result = await _run(monkeypatch, account, args, display)

    assert _outcomes(result) == {
        ("Trail", "remove", "Free Returns", "removed"),
        ("Trail", "add", "Free Returns", "added"),
    }
    callouts = {
        asset
        for kind, owner, asset, _type in account.links
        if (kind, owner) == ("campaigns", "10") and _type == "CALLOUT"
    }
    assert callouts and "71" not in callouts


async def test_an_asset_shown_as_already_linked_is_refused_when_the_link_has_gone(
    monkeypatch,
) -> None:
    account = _Account()
    args = _args([{"kind": "campaign", "campaign": _campaign("10"), "add": [_FREE_RETURNS]}])
    display = await _display(monkeypatch, account, args)
    account.links.discard(("campaigns", "10", "71", "CALLOUT"))

    result = await _run(monkeypatch, account, args, display)

    assert all(body["validateOnly"] for body in account.mutates)
    (row,) = result["results"][0]["data"]["outcomes"]
    assert (row["outcome"], row["error_code"]) == ("failed", "CHANGED_SINCE_APPROVAL")


async def test_changes_the_approver_was_not_shown_are_refused_and_never_sent(monkeypatch) -> None:
    account = _Account()
    shown = {
        "kind": "campaign",
        "campaign": _campaign("10"),
        "add": [{"type": "existing", "asset": _asset("72")}],
    }
    display = await _display(monkeypatch, account, _args([shown]))
    checked = len(account.mutates)
    args = _args(
        [
            # A row added to a target that was shown, and a target that wasn't shown at all.
            {**shown, "remove": [_asset("71")]},
            {"kind": "campaign", "campaign": _campaign("20"), "add": [_NEW_SITELINK]},
        ],
        [{"asset": _asset("71"), "content": {"type": "callout", "text": "Free 60-Day Returns"}}],
    )

    result = await _run(monkeypatch, account, args, display)

    (sent,) = account.mutates[checked:]
    assert sent["mutateOperations"] == [
        {
            "campaignAssetOperation": {
                "create": {
                    "campaign": f"{_C}/campaigns/10",
                    "asset": f"{_C}/assets/72",
                    "fieldType": "CALLOUT",
                }
            }
        }
    ]
    rows = result["results"][0]["data"]["outcomes"]
    assert {(row["action"], row["asset_label"], row["outcome"]) for row in rows} == {
        ("add", "Next-Day Delivery", "added"),
        ("remove", "Asset", "failed"),
        ("add", "Size Guide", "failed"),
        ("change", "Free 60-Day Returns", "failed"),
    }
    assert {row["message"] for row in rows if row["outcome"] == "failed"} == {tool_module.NOT_SHOWN}


async def test_a_new_asset_google_rejected_in_the_dry_run_is_left_out_of_the_build(
    monkeypatch,
) -> None:
    account = _Account()
    account.rejected_callout = "Best In The World"
    args = _args(
        [
            {
                "kind": "campaign",
                "campaign": _campaign("20"),
                "add": [{"type": "callout", "text": "Best In The World"}, _FREE_RETURNS],
            }
        ]
    )

    display = await _display(monkeypatch, account, args)
    checked = len(account.mutates)
    result = await _run(monkeypatch, account, args, display)

    (build,) = account.mutates[checked:]
    assert [
        operation["assetOperation"]["create"]["calloutAsset"]["calloutText"]
        for operation in build["mutateOperations"]
        if "assetOperation" in operation
    ] == ["Free Returns"]
    assert _outcomes(result) == {
        ("Road", "add", "Best In The World", "failed"),
        ("Road", "add", "Free Returns", "added"),
    }


def test_image_and_video_assets_are_refused_wherever_a_reference_is_taken() -> None:
    with pytest.raises(ValidationError, match="Only sitelinks and callouts"):
        _args(
            [{"kind": "campaign", "campaign": _campaign("10"), "remove": [_asset("71", "IMAGE")]}]
        )
    with pytest.raises(ValidationError, match="same type"):
        _args(
            [],
            [
                {
                    "asset": _asset("71", "YOUTUBE_VIDEO"),
                    "content": {"type": "callout", "text": "Watch Now"},
                }
            ],
        )
