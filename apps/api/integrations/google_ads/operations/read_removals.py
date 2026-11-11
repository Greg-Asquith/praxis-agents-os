# apps/api/integrations/google_ads/operations/read_removals.py

"""Reads what `google_ads_remove_objects` removes, what each removal takes with it, and its users."""

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .count_label_associations import count_label_associations
from .read_status import read_statuses
from .utils import nonnegative_int, stream_rows

# Rows read per dependant or user query; one more marks the counts as lower bounds.
DEPENDANT_ROW_BOUND = 10_000
# The campaigns named per budget or strategy still in use; the count covers the rest.
_LISTED_USERS = 3
_STATUS_KINDS = frozenset({"campaign", "ad_group", "ad", "keyword", "asset_group"})
_RESOURCE_NAME = re.compile(
    r"customers/\d+/(?:campaigns|adGroups|assetGroups|campaignBudgets|labels|biddingStrategies"
    r"|sharedSets)/\d+"
    r"|customers/\d+/(?:adGroupAds|adGroupCriteria)/\d+~\d+"
)
# Each kind outside campaigns' tree: its GAQL resource and the row key Google returns it under.
_SHARED_QUERIES = {
    "budget": ("campaign_budget", "campaignBudget"),
    "label": ("label", "label"),
    "bidding_strategy": ("bidding_strategy", "biddingStrategy"),
    "negative_keyword_list": ("shared_set", "sharedSet"),
}
# The campaign field that names each kind a campaign uses.
_USER_FIELDS = {
    "budget": "campaign.campaign_budget",
    "bidding_strategy": "campaign.bidding_strategy",
}
# What removing a campaign or ad group takes with it: (count key, GAQL resource, filter).
_DEPENDANTS = {
    # A child keeps its own status when its ad group is removed, so the ad group is checked too.
    "campaign": (
        ("ad_groups", "ad_group", "ad_group.status != 'REMOVED'"),
        (
            "ads",
            "ad_group_ad",
            "ad_group.status != 'REMOVED' AND ad_group_ad.status != 'REMOVED'",
        ),
        (
            "keywords",
            "ad_group_criterion",
            "ad_group.status != 'REMOVED' AND ad_group_criterion.status != 'REMOVED'",
        ),
    ),
    "ad_group": (
        ("ads", "ad_group_ad", "ad_group_ad.status != 'REMOVED'"),
        ("keywords", "ad_group_criterion", "ad_group_criterion.status != 'REMOVED'"),
    ),
}
_KEYWORDS_ONLY = "ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE"
_PARENTS = {"campaign": ("campaign", "campaign"), "ad_group": ("ad_group", "adGroup")}


@dataclass(frozen=True, slots=True)
class RemovalTarget:
    """One object as removal sees it: its status, where it sits, and what it takes with it."""

    kind: str
    name: str
    # `REMOVED` once Google has removed it.
    status: str
    # The campaign it sits in, or is; None for objects outside campaigns.
    campaign_id: str | None = None
    campaign_name: str | None = None
    ad_group_name: str | None = None
    # Counts by kind, such as `{"ads": 6, "keywords": 92}`; filled by `with_dependants`.
    dependants: Mapping[str, int] = field(default_factory=dict)
    # True when a count stopped at `DEPENDANT_ROW_BOUND`.
    truncated: bool = False
    # The first campaigns still using a budget or portfolio strategy, which blocks its removal;
    # `dependants["campaigns"]` counts them all.
    users: tuple[str, ...] = ()


async def read_removal_targets(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    objects: Sequence[tuple[str, str]],
    with_dependants: bool,
) -> dict[str, RemovalTarget]:
    """Returns each `(kind, resource_name)` object by resource name, removed ones included.

    Each kind is one read. With `with_dependants`, it also counts what removing each campaign
    or ad group takes with it, where each label is used, and the campaigns still using each
    budget or strategy. Objects Google doesn't return are left out.
    """
    prefix = f"customers/{normalize_customer_id(customer_id)}/"
    by_kind: dict[str, list[str]] = defaultdict(list)
    for kind, resource_name in objects:
        if (
            kind not in _STATUS_KINDS | _SHARED_QUERIES.keys()
            or _RESOURCE_NAME.fullmatch(resource_name) is None
            or not resource_name.startswith(prefix)
        ):
            raise ValueError(
                "Google Ads removal reads need a known kind and this account's objects"
            )
        by_kind[kind].append(resource_name)
    kwargs = {"client": client, "customer_id": customer_id, "login_customer_id": login_customer_id}
    status_objects = [
        (kind, name) for kind, names in by_kind.items() if kind in _STATUS_KINDS for name in names
    ]
    statuses = await read_statuses(**kwargs, objects=status_objects) if status_objects else {}
    targets = {
        name: RemovalTarget(
            kind=item.kind,
            name=item.name,
            status=item.status,
            campaign_id=item.campaign_id or None,
            campaign_name=item.campaign_name or None,
            ad_group_name=item.ad_group_name,
        )
        for name, item in statuses.items()
    }
    # One kind at a time: concurrent requests would share the caller's database session.
    for kind in (kind for kind in _SHARED_QUERIES if kind in by_kind):
        targets.update(await _read_shared(**kwargs, kind=kind, names=by_kind[kind]))
    if not with_dependants:
        return targets
    for kind in (kind for kind in _DEPENDANTS if kind in by_kind):
        await _count_dependants(**kwargs, kind=kind, targets=targets, names=by_kind[kind])
    for kind in (kind for kind in _USER_FIELDS if kind in by_kind):
        await _read_users(**kwargs, kind=kind, targets=targets, names=by_kind[kind])
    if by_kind.get("label"):
        await _count_label_uses(**kwargs, targets=targets, names=by_kind["label"])
    if by_kind.get("negative_keyword_list"):
        await _count_list_uses(**kwargs, targets=targets, names=by_kind["negative_keyword_list"])
    return targets


async def _read_shared(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    kind: str,
    names: Sequence[str],
) -> dict[str, RemovalTarget]:
    resource, row_key = _SHARED_QUERIES[kind]
    fields = [f"{resource}.resource_name", f"{resource}.name", f"{resource}.status"]
    if kind == "negative_keyword_list":
        fields.append("shared_set.member_count")
    rows = await _search(
        client,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        query=(
            f"SELECT {', '.join(fields)} FROM {resource} "  # noqa: S608 -- validated resource names
            f"WHERE {resource}.resource_name IN ({_quoted(names)})"
        ),
        max_rows=len(set(names)),
    )
    wanted = set(names)
    targets: dict[str, RemovalTarget] = {}
    for row in rows:
        item = row.get(row_key)
        if not isinstance(item, Mapping) or item.get("resourceName") not in wanted:
            continue
        targets[item["resourceName"]] = RemovalTarget(
            kind=kind,
            name=str(item.get("name") or ""),
            status=str(item.get("status") or ""),
            # The negative keywords in a list go with it.
            dependants={"keywords": nonnegative_int(item.get("memberCount")) or 0}
            if kind == "negative_keyword_list"
            else {},
        )
    return targets


async def _count_dependants(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    kind: str,
    targets: dict[str, RemovalTarget],
    names: Sequence[str],
) -> None:
    """Counts the live ad groups, ads, and keywords under each campaign or ad group."""
    parent, parent_key = _PARENTS[kind]
    live = [name for name in names if (target := targets.get(name)) and target.status != "REMOVED"]
    if not live:
        return
    counts: dict[str, dict[str, int]] = {name: {} for name in live}
    truncated = False
    for key, resource, condition in _DEPENDANTS[kind]:
        where = f"{parent}.resource_name IN ({_quoted(live)}) AND {condition}"
        if key == "keywords":
            where = f"{where} AND {_KEYWORDS_ONLY}"
        rows = await _search(
            client,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            query=(
                f"SELECT {parent}.resource_name FROM {resource} "  # noqa: S608 -- validated resource names
                f"WHERE {where} LIMIT {DEPENDANT_ROW_BOUND + 1}"
            ),
            max_rows=DEPENDANT_ROW_BOUND + 1,
        )
        truncated = truncated or len(rows) > DEPENDANT_ROW_BOUND
        for row in rows[:DEPENDANT_ROW_BOUND]:
            owner = row.get(parent_key)
            name = owner.get("resourceName") if isinstance(owner, Mapping) else None
            if name in counts:
                counts[name][key] = counts[name].get(key, 0) + 1
    for name, found in counts.items():
        targets[name] = replace(targets[name], dependants=found, truncated=truncated)


async def _read_users(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    kind: str,
    targets: dict[str, RemovalTarget],
    names: Sequence[str],
) -> None:
    """Names the campaigns that still use each budget or portfolio strategy."""
    live = [name for name in names if (target := targets.get(name)) and target.status != "REMOVED"]
    if not live:
        return
    user_field = _USER_FIELDS[kind]
    rows = await _search(
        client,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        query=(
            f"SELECT campaign.name, {user_field} FROM campaign "  # noqa: S608 -- validated resource names
            f"WHERE campaign.status != 'REMOVED' AND {user_field} IN ({_quoted(live)}) "
            f"LIMIT {DEPENDANT_ROW_BOUND + 1}"
        ),
        max_rows=DEPENDANT_ROW_BOUND + 1,
    )
    users: dict[str, list[str]] = {name: [] for name in live}
    used_key = "campaignBudget" if kind == "budget" else "biddingStrategy"
    for row in rows[:DEPENDANT_ROW_BOUND]:
        campaign = row.get("campaign")
        if isinstance(campaign, Mapping) and campaign.get(used_key) in users:
            users[campaign[used_key]].append(str(campaign.get("name") or "Campaign"))
    for name, found in users.items():
        targets[name] = replace(
            targets[name],
            users=tuple(found[:_LISTED_USERS]),
            dependants={"campaigns": len(found)},
            truncated=len(rows) > DEPENDANT_ROW_BOUND,
        )


async def _count_list_uses(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    targets: dict[str, RemovalTarget],
    names: Sequence[str],
) -> None:
    """Counts the campaigns each negative keyword list is applied to; removal detaches it."""
    live = [name for name in names if (target := targets.get(name)) and target.status != "REMOVED"]
    if not live:
        return
    rows = await _search(
        client,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        query=(
            "SELECT campaign_shared_set.shared_set FROM campaign_shared_set "  # noqa: S608 -- validated resource names
            f"WHERE campaign_shared_set.shared_set IN ({_quoted(live)}) "
            f"AND campaign_shared_set.status = 'ENABLED' LIMIT {DEPENDANT_ROW_BOUND + 1}"
        ),
        max_rows=DEPENDANT_ROW_BOUND + 1,
    )
    counts = dict.fromkeys(live, 0)
    for row in rows[:DEPENDANT_ROW_BOUND]:
        use = row.get("campaignSharedSet")
        name = use.get("sharedSet") if isinstance(use, Mapping) else None
        if name in counts:
            counts[name] += 1
    for name, count in counts.items():
        targets[name] = replace(
            targets[name],
            dependants={**targets[name].dependants, "campaigns": count},
            truncated=len(rows) > DEPENDANT_ROW_BOUND,
        )


async def _count_label_uses(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    targets: dict[str, RemovalTarget],
    names: Sequence[str],
) -> None:
    """Counts the campaigns, ad groups, ads, and keywords each label is on."""
    live = [name for name in names if (target := targets.get(name)) and target.status != "REMOVED"]
    if not live:
        return
    counts = await count_label_associations(
        client,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        label_ids=[name.rsplit("/", 1)[-1] for name in live],
    )
    for name in live:
        label = counts[name.rsplit("/", 1)[-1]]
        targets[name] = replace(
            targets[name],
            dependants={
                "campaigns": label.campaign,
                "ad_groups": label.ad_group,
                "ads": label.ad,
                "keywords": label.keyword,
            },
            truncated=label.truncated,
        )


def _quoted(names: Sequence[str]) -> str:
    return ", ".join(f"'{name}'" for name in sorted(set(names)))


async def _search(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    query: str,
    max_rows: int,
) -> list[dict[str, Any]]:
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_removals",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    return stream_rows(payload, max_rows=max_rows)
