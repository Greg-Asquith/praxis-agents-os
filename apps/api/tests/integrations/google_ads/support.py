"""Shared fakes and builders for Google Ads integration tests."""

from typing import Any
from uuid import uuid4

from integrations.google_ads.operations.mutation_outcomes import (
    AD_GROUP_KEYWORD_MUTATION_SPEC,
    CAMPAIGN_KEYWORD_MUTATION_SPEC,
    SHARED_SET_KEYWORD_MUTATION_SPEC,
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_keyword_mutation_ledger,
    build_mutation_ledger,
)
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignReference,
)
from services.integrations.context.domain import ResolvedContextEntry


async def _static_token(_force: bool) -> str:
    return "access-token"


def mutation_ledger(result: dict[str, Any]) -> GoogleAdsMutationLedger:
    """Builds a real ledger from a compact projected result fixture."""
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
        spec = {
            "keyword_errors": SHARED_SET_KEYWORD_MUTATION_SPEC,
            "campaign_errors": CAMPAIGN_KEYWORD_MUTATION_SPEC,
            "ad_group_errors": AD_GROUP_KEYWORD_MUTATION_SPEC,
        }[errors_key]
        parent_fields, skipped_indices, submitted, outcomes = _ledger_inputs(
            applied=result[applied_key],
            skipped=result[skipped_key],
            failed=result[errors_key],
        )
        return build_keyword_mutation_ledger(
            spec=spec,
            action="add" if applied_key == "added" else "remove",
            parent_fields=parent_fields,
            skipped_indices=skipped_indices,
            submitted=submitted,
            outcomes=outcomes,
        )

    if "list_errors" in result:
        applied = [
            {"name": str(name), "resource_name": str(resource_name)}
            for name, resource_name in zip(
                result.get("created_names", ()), result.get("resource_names", ()), strict=True
            )
        ]
        skipped = [{"name": str(name)} for name in result.get("skipped_existing", ())]
        parent_fields, skipped_indices, submitted, outcomes = _ledger_inputs(
            applied=applied,
            skipped=skipped,
            failed=result["list_errors"],
        )
        return build_mutation_ledger(
            family="negative_keyword_lists",
            action="create",
            parent_fields=parent_fields,
            skipped_indices=skipped_indices,
            submitted=submitted,
            outcomes=outcomes,
            projection=GoogleAdsMutationProjection(
                applied_key="created",
                skipped_key="skipped_existing",
                errors_key="list_errors",
            ),
        )

    if "campaign_errors" in result:
        applied = []
        for resource_name in result.get("resource_names", ()):
            terminal = str(resource_name).rsplit("/", 1)[-1]
            applied.append(
                {
                    "campaign_id": terminal.split("~", 1)[0],
                    "resource_name": str(resource_name),
                }
            )
        skip_key = "skipped_existing" if "skipped_existing" in result else "not_found"
        skipped = [{"campaign_id": str(value)} for value in result.get(skip_key, ())]
        parent_fields, skipped_indices, submitted, outcomes = _ledger_inputs(
            applied=applied,
            skipped=skipped,
            failed=result["campaign_errors"],
        )
        is_link = skip_key in result
        return build_mutation_ledger(
            family="campaign_shared_set_links" if is_link else "campaign_status",
            action=("link" if skip_key == "skipped_existing" else "unlink")
            if is_link
            else "update",
            parent_fields=parent_fields,
            skipped_indices=skipped_indices,
            submitted=submitted,
            outcomes=outcomes,
            projection=GoogleAdsMutationProjection(
                applied_key="applied" if is_link else "updated",
                skipped_key=skip_key if is_link else "skipped",
                errors_key="campaign_errors",
            ),
        )

    raise ValueError("Mutation ledger fixture requires a recognized total result")


def _ledger_inputs(
    *,
    applied: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    failed: list[dict[str, Any]],
) -> tuple[
    list[dict[str, str]],
    dict[int, str],
    list[tuple[int, dict[str, str]]],
    list[tuple[str, str | None, str | None, str | None]],
]:
    parent_fields: list[dict[str, str]] = []
    skipped_indices: dict[int, str] = {}
    submitted: list[tuple[int, dict[str, str]]] = []
    outcomes: list[tuple[str, str | None, str | None, str | None]] = []

    for item in applied:
        fields = _outcome_fields(item)
        parent_fields.append(fields)
        submitted.append((len(parent_fields) - 1, fields))
        outcomes.append(("applied", str(item["resource_name"]), None, None))
    for item in skipped:
        parent_fields.append(_outcome_fields(item))
        skipped_indices[len(parent_fields) - 1] = "already_satisfied"
    for item in failed:
        fields = _outcome_fields(item)
        parent_fields.append(fields)
        submitted.append((len(parent_fields) - 1, fields))
        outcomes.append(
            (
                "failed",
                None,
                str(item.get("error_code", "unknown")),
                str(item.get("message", "provider rejected the mutation")),
            )
        )
    return parent_fields, skipped_indices, submitted, outcomes


def _outcome_fields(item: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in item.items()
        if key not in {"resource_name", "message", "error_code", "scope"}
    }


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
                    "status": "ENABLED",
                }
            }
            for customer_id, level, manager in customers
        ]
    }
