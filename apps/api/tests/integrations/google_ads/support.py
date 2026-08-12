"""Shared fakes and builders for Google Ads integration tests."""

from typing import Any
from uuid import uuid4

from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationEffect,
    GoogleAdsMutationParent,
    freeze_fields,
)
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignReference,
)
from services.integrations.context.domain import ResolvedContextEntry


async def _static_token(_force: bool) -> str:
    return "access-token"


class _MutationLedgerDouble(dict[str, Any]):
    """Suite-local stand-in for isolated provider-operation mocks."""

    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__(result)
        self.parents = _parents_from_result(result)

    def require_verified(self) -> None:
        return None

    def result(self) -> dict[str, Any]:
        return dict(self)


def mutation_ledger_double(result: dict[str, Any]) -> _MutationLedgerDouble:
    return _MutationLedgerDouble(result)


def _parents_from_result(result: dict[str, Any]) -> tuple[GoogleAdsMutationParent, ...]:
    parents: list[GoogleAdsMutationParent] = []
    slot = 0

    def applied(fields: dict[str, str], external_ref: str) -> None:
        nonlocal slot
        parents.append(
            GoogleAdsMutationParent(
                identity=freeze_fields(fields),
                decision="submit",
                effects=(
                    GoogleAdsMutationEffect(
                        slot=slot,
                        fields=freeze_fields(fields),
                        outcome="applied",
                        external_ref=external_ref,
                    ),
                ),
            )
        )
        slot += 1

    def skipped(fields: dict[str, str]) -> None:
        parents.append(
            GoogleAdsMutationParent(
                identity=freeze_fields(fields),
                decision="skipped",
                skip_reason="already_satisfied",
            )
        )

    def failed(fields: dict[str, str], error: dict[str, Any]) -> None:
        nonlocal slot
        parents.append(
            GoogleAdsMutationParent(
                identity=freeze_fields(fields),
                decision="submit",
                effects=(
                    GoogleAdsMutationEffect(
                        slot=slot,
                        fields=freeze_fields(fields),
                        outcome="failed",
                        error_code=str(error.get("error_code", "unknown")),
                        message=str(error.get("message", "provider rejected the mutation")),
                    ),
                ),
            )
        )
        slot += 1

    applied_key = "added" if "added" in result else "removed" if "removed" in result else None
    skipped_key = (
        "skipped_existing"
        if "skipped_existing" in result
        else "not_found"
        if "not_found" in result
        else None
    )
    errors_key = next(
        (key for key in ("keyword_errors", "campaign_errors", "ad_group_errors") if key in result),
        None,
    )
    if applied_key is not None and skipped_key is not None and errors_key is not None:
        for item in result[applied_key]:
            fields = {
                key: str(value)
                for key, value in item.items()
                if key not in {"resource_name", "message", "error_code", "scope"}
            }
            applied(fields, str(item["resource_name"]))
        for item in result[skipped_key]:
            skipped({key: str(value) for key, value in item.items()})
        for error in result[errors_key]:
            fields = {
                key: str(value)
                for key, value in error.items()
                if key not in {"message", "error_code", "scope"}
            }
            if fields:
                failed(fields, error)
        return tuple(parents)

    if "list_errors" in result:
        for name, resource_name in zip(
            result.get("created_names", ()), result.get("resource_names", ()), strict=True
        ):
            applied({"name": str(name)}, str(resource_name))
        for name in result.get("skipped_existing", ()):
            skipped({"name": str(name)})
        for error in result["list_errors"]:
            if name := str(error.get("name", "")):
                failed({"name": name}, error)
        return tuple(parents)

    if "campaign_errors" in result:
        for resource_name in result.get("resource_names", ()):
            terminal = str(resource_name).rsplit("/", 1)[-1]
            applied({"campaign_id": terminal.split("~", 1)[0]}, str(resource_name))
        for campaign_id in result.get("skipped_existing", result.get("not_found", ())):
            skipped({"campaign_id": str(campaign_id)})
        for error in result["campaign_errors"]:
            if campaign_id := str(error.get("campaign_id", "")):
                failed({"campaign_id": campaign_id}, error)
        return tuple(parents)

    raise ValueError("Mutation ledger test double requires a recognized total result")


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
