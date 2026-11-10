# apps/api/integrations/google_ads/operations/negative_keyword_criteria.py

"""Reads negative keywords on campaigns, ad groups, and lists, and the keywords they could block."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import stream_rows

# Google allows 5,000 keywords a list; these only stop an unbounded read.
_MAX_NEGATIVES = 100_000
_MAX_BID_KEYWORDS = 100_000
_MAX_LISTS = 10_000
_TOO_MANY = (
    "These campaigns hold too many keywords to check at once. Change fewer campaigns or lists."
)


@dataclass(frozen=True, slots=True)
class LiveOwner:
    """A campaign, ad group, or list that negatives belong to."""

    resource_name: str
    name: str
    status: str
    campaign: str | None = None


@dataclass(frozen=True, slots=True)
class BidKeyword:
    """A keyword the account bids on, which a negative in its scope could block."""

    campaign: str
    ad_group: str
    ad_group_name: str
    text: str


@dataclass(frozen=True, slots=True)
class LiveNegatives:
    owners: Mapping[str, LiveOwner] = field(default_factory=dict)
    # By `negative_key` or `list_use_key`, the live resource name.
    criteria: Mapping[str, str] = field(default_factory=dict)
    # Each list's keywords as `(text, match type)`.
    list_keywords: Mapping[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    # Each list's campaigns.
    list_campaigns: Mapping[str, frozenset[str]] = field(default_factory=dict)
    # Lists that aren't removed, by name in lower case.
    list_names: Mapping[str, str] = field(default_factory=dict)
    bid_keywords: tuple[BidKeyword, ...] = ()

    def values(self) -> dict[str, dict[str, Any]]:
        """Returns each negative and list use by edit key, for the edit seam."""
        return {key: {"resourceName": name} for key, name in self.criteria.items()}


def negative_key(owner: str, text: str, match_type: str) -> str:
    """Names one negative on its campaign, ad group, or list; Google ignores case."""
    return f"{owner}/negative/{match_type}/{' '.join(text.casefold().split())}"


def list_use_key(campaign: str, shared_set: str) -> str:
    """Names a campaign's use of a list, including a list the same request creates."""
    return f"{campaign}/uses/{shared_set}"


def blocks(negative: str, match_type: str, keyword: str) -> bool:
    """Whether a negative blocks searches for the keyword's own words."""
    words = keyword.casefold().split()
    blocked = negative.casefold().split()
    if match_type == "EXACT":
        return words == blocked
    if match_type == "PHRASE":
        size = len(blocked)
        return any(words[index : index + size] == blocked for index in range(len(words) - size + 1))
    return set(blocked) <= set(words)


async def read_negative_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
    ad_group_ids: Sequence[str],
    shared_set_ids: Sequence[str],
    list_campaign_ids: Sequence[str],
    check_keywords: bool,
) -> LiveNegatives:
    """Reads the targets that exist, removed ones included, and their negatives.

    `campaign_ids` and `ad_group_ids` hold negatives; `list_campaign_ids` are campaigns a list
    is applied to or taken from. With `check_keywords`, it also reads the keywords bid on in
    every campaign and ad group whose searches the negatives would cover.

    Raises:
        IntegrationValidationError: When the targets hold too many keywords to compare.
    """
    ids = [*campaign_ids, *ad_group_ids, *shared_set_ids, *list_campaign_ids]
    if any(not value.isdigit() for value in ids):
        raise ValueError("Google Ads ids must contain only digits")
    read = _Reader(client, normalize_customer_id(customer_id), login_customer_id)
    campaigns = sorted({*campaign_ids, *list_campaign_ids})
    owners, ad_groups, negatives, lists, list_keywords, uses = await asyncio.gather(
        read.campaigns(campaigns),
        read.ad_groups(sorted(set(ad_group_ids))),
        read.owner_negatives(sorted(set(campaign_ids)), sorted(set(ad_group_ids))),
        read.lists(),
        read.list_keywords(sorted(set(shared_set_ids))),
        read.list_uses(sorted(set(shared_set_ids))),
    )
    all_owners = {**owners, **ad_groups, **lists}
    criteria = {**negatives, **list_keywords[0], **uses[0]}
    bid_keywords: tuple[BidKeyword, ...] = ()
    if check_keywords:
        used = {campaign for names in uses[1].values() for campaign in names}
        scoped = {*campaign_ids, *list_campaign_ids, *(name.rpartition("/")[2] for name in used)}
        bid_keywords = await read.bid_keywords(sorted(scoped), sorted(set(ad_group_ids)))
    return LiveNegatives(
        owners=all_owners,
        criteria=criteria,
        list_keywords=list_keywords[1],
        list_campaigns=uses[1],
        list_names={
            owner.name.casefold(): name
            for name, owner in lists.items()
            if owner.status != "REMOVED"
        },
        bid_keywords=bid_keywords,
    )


@dataclass(frozen=True, slots=True)
class _Reader:
    client: GoogleAdsClient
    customer: str
    login_customer_id: str

    async def _rows(self, query: str, operation: str, max_rows: int) -> list[dict[str, Any]]:
        payload = await self.client.post(
            f"customers/{self.customer}/googleAds:searchStream",
            operation=operation,
            policy=IntegrationRequestPolicy.READ,
            login_customer_id=self.login_customer_id,
            json={"query": query},
        )
        rows = stream_rows(payload, max_rows=max_rows)
        if len(rows) >= max_rows:
            raise IntegrationValidationError(
                _TOO_MANY,
                provider_key="google_ads",
                failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
            )
        return rows

    def _name(self, collection: str, value: Any) -> str:
        return f"customers/{self.customer}/{collection}/{value}"

    async def campaigns(self, ids: Sequence[str]) -> dict[str, LiveOwner]:
        if not ids:
            return {}
        rows = await self._rows(
            "SELECT campaign.id, campaign.name, campaign.status FROM campaign "  # noqa: S608 -- digit-only ids
            f"WHERE campaign.id IN ({', '.join(ids)})",
            "read_negative_keyword_campaigns",
            len(ids) + 1,
        )
        owners = {}
        for row in rows:
            campaign = row.get("campaign") or {}
            name = self._name("campaigns", campaign.get("id"))
            owners[name] = LiveOwner(
                name, str(campaign.get("name") or name), str(campaign.get("status") or "UNKNOWN")
            )
        return owners

    async def ad_groups(self, ids: Sequence[str]) -> dict[str, LiveOwner]:
        if not ids:
            return {}
        rows = await self._rows(
            "SELECT ad_group.id, ad_group.name, ad_group.status, campaign.id FROM ad_group "  # noqa: S608 -- digit-only ids
            f"WHERE ad_group.id IN ({', '.join(ids)})",
            "read_negative_keyword_ad_groups",
            len(ids) + 1,
        )
        owners = {}
        for row in rows:
            ad_group = row.get("adGroup") or {}
            name = self._name("adGroups", ad_group.get("id"))
            owners[name] = LiveOwner(
                name,
                str(ad_group.get("name") or name),
                str(ad_group.get("status") or "UNKNOWN"),
                campaign=self._name("campaigns", (row.get("campaign") or {}).get("id")),
            )
        return owners

    async def owner_negatives(
        self, campaign_ids: Sequence[str], ad_group_ids: Sequence[str]
    ) -> dict[str, str]:
        queries = [
            (resource, "campaigns" if resource == "campaign" else "adGroups", ids)
            for resource, ids in (("campaign", campaign_ids), ("ad_group", ad_group_ids))
            if ids
        ]
        results = await asyncio.gather(
            *(
                self._rows(
                    f"SELECT {resource}.id, {resource}_criterion.resource_name, "  # noqa: S608 -- fixed resources and digit-only ids
                    f"{resource}_criterion.keyword.text, {resource}_criterion.keyword.match_type "
                    f"FROM {resource}_criterion WHERE {resource}_criterion.negative = TRUE "
                    f"AND {resource}_criterion.type = 'KEYWORD' "
                    f"AND {resource}_criterion.status != 'REMOVED' "
                    f"AND {resource}.id IN ({', '.join(ids)})",
                    f"read_{resource}_negative_keywords",
                    _MAX_NEGATIVES,
                )
                for resource, _collection, ids in queries
            )
        )
        criteria: dict[str, str] = {}
        for (resource, collection, _ids), rows in zip(queries, results, strict=True):
            owner_key = "campaign" if resource == "campaign" else "adGroup"
            for row in rows:
                criterion = row.get(f"{owner_key}Criterion") or {}
                keyword = criterion.get("keyword") or {}
                name = criterion.get("resourceName")
                if isinstance(name, str) and keyword.get("text") and keyword.get("matchType"):
                    owner = self._name(collection, (row.get(owner_key) or {}).get("id"))
                    key = negative_key(owner, str(keyword["text"]), str(keyword["matchType"]))
                    criteria[key] = name
        return criteria

    async def lists(self) -> dict[str, LiveOwner]:
        rows = await self._rows(
            "SELECT shared_set.id, shared_set.name, shared_set.status FROM shared_set "
            "WHERE shared_set.type = 'NEGATIVE_KEYWORDS'",
            "read_negative_keyword_lists",
            _MAX_LISTS,
        )
        owners = {}
        for row in rows:
            shared_set = row.get("sharedSet") or {}
            name = self._name("sharedSets", shared_set.get("id"))
            owners[name] = LiveOwner(
                name,
                str(shared_set.get("name") or name),
                str(shared_set.get("status") or "UNKNOWN"),
            )
        return owners

    async def list_keywords(
        self, ids: Sequence[str]
    ) -> tuple[dict[str, str], dict[str, tuple[tuple[str, str], ...]]]:
        if not ids:
            return {}, {}
        rows = await self._rows(
            "SELECT shared_set.id, shared_criterion.resource_name, "  # noqa: S608 -- digit-only ids
            "shared_criterion.keyword.text, shared_criterion.keyword.match_type "
            "FROM shared_criterion WHERE shared_criterion.type = 'KEYWORD' "
            f"AND shared_set.id IN ({', '.join(ids)})",
            "read_negative_keyword_list_keywords",
            _MAX_NEGATIVES,
        )
        criteria: dict[str, str] = {}
        keywords: dict[str, list[tuple[str, str]]] = {}
        for row in rows:
            criterion = row.get("sharedCriterion") or {}
            keyword = criterion.get("keyword") or {}
            name = criterion.get("resourceName")
            text, match_type = keyword.get("text"), keyword.get("matchType")
            if isinstance(name, str) and text and match_type:
                owner = self._name("sharedSets", (row.get("sharedSet") or {}).get("id"))
                criteria[negative_key(owner, str(text), str(match_type))] = name
                keywords.setdefault(owner, []).append((str(text), str(match_type)))
        return criteria, {owner: tuple(items) for owner, items in keywords.items()}

    async def list_uses(
        self, ids: Sequence[str]
    ) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
        if not ids:
            return {}, {}
        rows = await self._rows(
            "SELECT campaign_shared_set.resource_name, campaign_shared_set.campaign, "  # noqa: S608 -- digit-only ids
            "campaign_shared_set.shared_set FROM campaign_shared_set "
            "WHERE campaign_shared_set.status = 'ENABLED' "
            f"AND shared_set.id IN ({', '.join(ids)})",
            "read_negative_keyword_list_campaigns",
            _MAX_NEGATIVES,
        )
        criteria: dict[str, str] = {}
        campaigns: dict[str, set[str]] = {}
        for row in rows:
            use = row.get("campaignSharedSet") or {}
            name, campaign, shared_set = (
                use.get("resourceName"),
                use.get("campaign"),
                use.get("sharedSet"),
            )
            if isinstance(name, str) and isinstance(campaign, str) and isinstance(shared_set, str):
                criteria[list_use_key(campaign, shared_set)] = name
                campaigns.setdefault(shared_set, set()).add(campaign)
        return criteria, {owner: frozenset(items) for owner, items in campaigns.items()}

    async def bid_keywords(
        self, campaign_ids: Sequence[str], ad_group_ids: Sequence[str]
    ) -> tuple[BidKeyword, ...]:
        filters = [
            f"{resource}.id IN ({', '.join(ids)})"
            for resource, ids in (("campaign", campaign_ids), ("ad_group", ad_group_ids))
            if ids
        ]
        results = await asyncio.gather(
            *(
                self._rows(
                    "SELECT campaign.id, ad_group.id, ad_group.name, "  # noqa: S608 -- fixed resources and digit-only ids
                    "ad_group_criterion.keyword.text FROM ad_group_criterion "
                    "WHERE ad_group_criterion.type = 'KEYWORD' "
                    "AND ad_group_criterion.negative = FALSE "
                    "AND ad_group_criterion.status != 'REMOVED' "
                    f"AND ad_group.status != 'REMOVED' AND {condition}",
                    "read_negative_keyword_bid_keywords",
                    _MAX_BID_KEYWORDS,
                )
                for condition in filters
            )
        )
        keywords: dict[tuple[str, str, str], BidKeyword] = {}
        for row in (row for rows in results for row in rows):
            ad_group = row.get("adGroup") or {}
            text = ((row.get("adGroupCriterion") or {}).get("keyword") or {}).get("text")
            if not text:
                continue
            keyword = BidKeyword(
                campaign=self._name("campaigns", (row.get("campaign") or {}).get("id")),
                ad_group=self._name("adGroups", ad_group.get("id")),
                ad_group_name=str(ad_group.get("name") or ""),
                text=str(text),
            )
            keywords[keyword.campaign, keyword.ad_group, keyword.text.casefold()] = keyword
        return tuple(keywords.values())
