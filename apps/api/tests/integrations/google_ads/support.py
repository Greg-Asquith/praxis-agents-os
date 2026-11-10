# apps/api/tests/integrations/google_ads/support.py

"""Shared fakes and builders for Google Ads integration tests."""

import re
from typing import Any
from uuid import uuid4

from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignReference,
)
from services.integrations.context.domain import ResolvedContextEntry


async def _static_token(_force: bool) -> str:
    return "access-token"


class _DiscoveryClient:
    def __init__(self, *, manager_access_role: str = "STANDARD") -> None:
        self.calls: list[dict[str, str]] = []
        self.manager_access_role = manager_access_role

    async def get(self, _path: str, **_kwargs):
        return {"resourceNames": ["customers/111"]}

    async def post(self, path: str, **kwargs):
        query = kwargs["json"]["query"]
        self.calls.append(
            {
                "path": path,
                "login_customer_id": kwargs["login_customer_id"],
                "query": query,
            }
        )
        if "customer_user_access" in query:
            customer_id = path.split("/")[1]
            if customer_id != "111":
                return [{"results": []}]
            return [
                {
                    "results": [
                        {
                            "customerUserAccess": {
                                "emailAddress": "agent@example.iam.gserviceaccount.com",
                                "accessRole": self.manager_access_role,
                            }
                        }
                    ]
                }
            ]
        customer_id = path.split("/")[1]
        if customer_id == "111":
            return [_hierarchy_page(("111", 0, True), ("222", 1, True))]
        if customer_id == "222":
            return [_hierarchy_page(("222", 0, True), ("333", 1, False))]
        return [_hierarchy_page((customer_id, 0, False))]


class _DuplicateRouteDiscoveryClient(_DiscoveryClient):
    async def get(self, _path: str, **_kwargs):
        return {"resourceNames": ["customers/333", "customers/111"]}

    async def post(self, path: str, **kwargs):
        query = kwargs["json"]["query"]
        if "customer_user_access" in query and path.startswith("customers/333/"):
            return [
                {
                    "results": [
                        {
                            "customerUserAccess": {
                                "emailAddress": "agent@example.iam.gserviceaccount.com",
                                "accessRole": "READ_ONLY",
                            }
                        }
                    ]
                }
            ]
        if "customer_user_access" not in query and path.startswith("customers/333/"):
            return [_hierarchy_page(("333", 0, False))]
        return await super().post(path, **kwargs)


class _OperationClient:
    def __init__(self, payload):
        self.payload = payload
        self.last_json = None
        self.last_login_customer_id = None

    async def post(self, _path: str, **kwargs):
        self.last_json = kwargs["json"]
        self.last_login_customer_id = kwargs["login_customer_id"]
        return self.payload


def _writable_google_ads_entry(*, write_allowed: bool = True) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=write_allowed,
        permissions_metadata={"login_customer_id": "999"},
    )


def _campaign_reference(
    entry: ResolvedContextEntry,
    campaign_id: str,
) -> GoogleAdsCampaignReference:
    return GoogleAdsCampaignReference(
        customer_id=entry.external_id,
        campaign_id=campaign_id,
        label=f"Campaign {campaign_id}",
    )


def _ad_group_reference(
    entry: ResolvedContextEntry,
    ad_group_id: str,
) -> GoogleAdsAdGroupReference:
    return GoogleAdsAdGroupReference(
        customer_id=entry.external_id,
        campaign_id="1",
        ad_group_id=ad_group_id,
        label=f"Ad Group {ad_group_id}",
        scope_label="Campaign 1",
    )


def _hierarchy_page(*customers: tuple[str, int, bool]) -> dict:
    return {
        "results": [
            {
                "customerClient": {
                    "clientCustomer": f"customers/{customer_id}",
                    "level": str(level),
                    "manager": manager,
                    "descriptiveName": f"Account {customer_id}",
                    "currencyCode": "GBP",
                    "timeZone": "Europe/London",
                    "status": "ENABLED",
                }
            }
            for customer_id, level, manager in customers
        ]
    }


_C = "customers/111"


class KeywordsAccount:
    """One Google Ads account: answers keyword, negative, and search term reads, and mutates."""

    def __init__(self) -> None:
        self.campaigns = {"10": "Trail", "20": "Road", "30": "Kids"}
        self.ad_groups = {"40": ("Trail Shoes", "10"), "41": ("Waterproof Shoes", "10")}
        self.lists = {"50": "Brand Protection"}
        # (collection, owner ID, text, match type) by resource name.
        self.negatives: dict[str, tuple[str, str, str, str]] = {
            f"{_C}/adGroupCriteria/40~7": ("adGroups", "40", "cheap", "BROAD"),
        }
        # (ad group ID, text, match type) by resource name.
        self.keywords: dict[str, tuple[str, str, str]] = {
            f"{_C}/adGroupCriteria/40~8": ("40", "trail running shoes", "PHRASE"),
        }
        # (ad group ID, term, status, clicks, cost micros, conversions).
        self.search_terms: list[tuple[str, str, str, int, int, float]] = []
        self.uses: set[tuple[str, str]] = set()
        self.mutates: list[dict[str, Any]] = []
        self.next_id = 900

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            return [{"results": self._search(body["query"])}]
        assert path == f"{_C}/googleAds:mutate"
        self.mutates.append(body)
        return self._mutate(body)

    def _search(self, query: str) -> list[dict[str, Any]]:
        match = re.search(r"IN \(([^)]*)\)", query)
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
                    "campaign": {"id": campaign},
                }
                for key, (name, campaign) in self.ad_groups.items()
                if key in ids
            ]
        if resource == "shared_set":
            return [
                {"sharedSet": {"id": key, "name": name, "status": "ENABLED"}}
                for key, name in self.lists.items()
            ]
        if resource == "search_term_view":
            return [
                {
                    "searchTermView": {"searchTerm": term, "status": status},
                    "adGroup": {"id": ad_group},
                    "metrics": {
                        "clicks": str(clicks),
                        "costMicros": str(cost),
                        "conversions": conversions,
                    },
                }
                for ad_group, term, status, clicks, cost, conversions in self.search_terms
                if ad_group in ids
            ]
        if resource == "ad_group_criterion" and "negative = FALSE" in query:
            return self._keyword_rows(ids, by_campaign="campaign.id IN" in query)
        if resource == "campaign_shared_set":
            return [
                {
                    "campaignSharedSet": {
                        "resourceName": f"{_C}/campaignSharedSets/{campaign}~{shared_set}",
                        "campaign": f"{_C}/campaigns/{campaign}",
                        "sharedSet": f"{_C}/sharedSets/{shared_set}",
                    }
                }
                for campaign, shared_set in self.uses
                if shared_set in ids
            ]
        collection, row_key, owner_key = {
            "campaign_criterion": ("campaigns", "campaignCriterion", "campaign"),
            "ad_group_criterion": ("adGroups", "adGroupCriterion", "adGroup"),
            "shared_criterion": ("sharedSets", "sharedCriterion", "sharedSet"),
        }[resource]
        return [
            {
                owner_key: {"id": owner},
                row_key: {
                    "resourceName": name,
                    "keyword": {"text": text, "matchType": match_type},
                },
            }
            for name, (kind, owner, text, match_type) in self.negatives.items()
            if kind == collection and owner in ids
        ]

    def _keyword_rows(self, ids: set[str], *, by_campaign: bool) -> list[dict[str, Any]]:
        rows = []
        for name, (ad_group, text, match_type) in self.keywords.items():
            ad_group_name, campaign = self.ad_groups[ad_group]
            if (campaign if by_campaign else ad_group) in ids:
                rows.append(
                    {
                        "campaign": {"id": campaign},
                        "adGroup": {"id": ad_group, "name": ad_group_name},
                        "adGroupCriterion": {
                            "resourceName": name,
                            "keyword": {"text": text, "matchType": match_type},
                        },
                    }
                )
        return rows

    def _mutate(self, body: dict[str, Any]) -> dict[str, Any]:
        created: dict[str, str] = {}
        responses = []
        for operation in body["mutateOperations"]:
            ((key, value),) = operation.items()
            name = self._apply(key.removesuffix("Operation"), value, created, body["validateOnly"])
            responses.append({key.replace("Operation", "Result"): {"resourceName": name}})
        return {"mutateOperationResponses": responses}

    def _apply(self, resource: str, value: dict, created: dict, dry: bool) -> str:
        if "remove" in value:
            if not dry:
                self.negatives.pop(value["remove"], None)
            return value["remove"]
        create = {
            key: created.get(item, item) if isinstance(item, str) else item
            for key, item in value["create"].items()
        }
        self.next_id += 1
        if resource == "sharedSet":
            name = f"{_C}/sharedSets/{self.next_id}"
            created[create["resourceName"]] = name
            if not dry:
                self.lists[str(self.next_id)] = create["name"]
            return name
        if resource == "campaignSharedSet":
            campaign, shared_set = (create[k].rsplit("/", 1)[1] for k in ("campaign", "sharedSet"))
            if not dry:
                self.uses.add((campaign, shared_set))
            return f"{_C}/campaignSharedSets/{campaign}~{shared_set}"
        owner_field, collection, criteria = {
            "campaignCriterion": ("campaign", "campaigns", "campaignCriteria"),
            "adGroupCriterion": ("adGroup", "adGroups", "adGroupCriteria"),
            "sharedCriterion": ("sharedSet", "sharedSets", "sharedCriteria"),
        }[resource]
        owner = create[owner_field].rsplit("/", 1)[1]
        name = f"{_C}/{criteria}/{owner}~{self.next_id}"
        if not dry:
            keyword = create["keyword"]
            if create.get("negative") is False:
                self.keywords[name] = (owner, keyword["text"], keyword["matchType"])
            else:
                self.negatives[name] = (collection, owner, keyword["text"], keyword["matchType"])
        return name
