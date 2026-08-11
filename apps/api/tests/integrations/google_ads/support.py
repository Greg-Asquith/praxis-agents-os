"""Shared fakes and builders for Google Ads integration tests."""

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


class _NegativeKeywordListClient:
    def __init__(self, *, search_payload, mutate_payload):
        self.search_payload = search_payload
        self.mutate_payload = mutate_payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            return self.search_payload
        if path.endswith("sharedSets:mutate"):
            return self.mutate_payload
        raise AssertionError(f"Unexpected Google Ads operation path: {path}")


class _NegativeKeywordClient:
    def __init__(self, *, search_payload, mutate_payload):
        self.search_payload = search_payload
        self.mutate_payload = mutate_payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            return self.search_payload
        if path.endswith("sharedCriteria:mutate"):
            return self.mutate_payload
        raise AssertionError(f"Unexpected Google Ads operation path: {path}")


class _CampaignSharedSetClient:
    def __init__(self, *, search_payload, mutate_payload):
        self.search_payload = search_payload
        self.mutate_payload = mutate_payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            return self.search_payload
        if path.endswith("campaignSharedSets:mutate"):
            return self.mutate_payload
        raise AssertionError(f"Unexpected Google Ads operation path: {path}")


class _CampaignNegativeKeywordClient:
    def __init__(self, *, search_payload, mutate_payload):
        self.search_payload = search_payload
        self.mutate_payload = mutate_payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            return self.search_payload
        if path.endswith("campaignCriteria:mutate"):
            return self.mutate_payload
        raise AssertionError(f"Unexpected Google Ads operation path: {path}")


class _AdGroupNegativeKeywordClient:
    def __init__(self, *, search_payload, mutate_payload):
        self.search_payload = search_payload
        self.mutate_payload = mutate_payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            return self.search_payload
        if path.endswith("adGroupCriteria:mutate"):
            return self.mutate_payload
        raise AssertionError(f"Unexpected Google Ads operation path: {path}")


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
        integration_resource_id=entry.integration_resource_id,
        external_id=campaign_id,
        label=f"Campaign {campaign_id}",
    )


def _ad_group_reference(
    entry: ResolvedContextEntry,
    ad_group_id: str,
) -> GoogleAdsAdGroupReference:
    return GoogleAdsAdGroupReference(
        integration_resource_id=entry.integration_resource_id,
        external_id=ad_group_id,
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
                    "status": "ENABLED",
                }
            }
            for customer_id, level, manager in customers
        ]
    }
