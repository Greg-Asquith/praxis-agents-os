# apps/api/integrations/meta_ads/discover_resources.py

"""Discover the ad accounts assigned to a Meta system user."""

from dataclasses import replace
from typing import Any

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.plugin import DiscoveredIntegrationResource, IntegrationDiscoveryResult
from utils.metadata import metadata_str

from .client import MetaAdsClient, normalize_ad_account_id
from .settings import meta_ads_settings

_ACCOUNT_STATUSES = {
    1: "ACTIVE",
    2: "DISABLED",
    3: "UNSETTLED",
    7: "PENDING_RISK_REVIEW",
    8: "PENDING_SETTLEMENT",
    9: "IN_GRACE_PERIOD",
    100: "PENDING_CLOSURE",
    101: "CLOSED",
    201: "ANY_ACTIVE",
    202: "ANY_CLOSED",
}
_ACCOUNT_FIELDS = "id,account_id,name,currency,timezone_name,account_status,user_tasks"


async def discover_resources(
    credential_value: str,
    _principal_label: str | None = None,
    _pacing_key: str = "",
) -> IntegrationDiscoveryResult:
    async def access_token() -> str:
        return credential_value

    client = MetaAdsClient(access_token, app_secret=meta_ads_settings.META_ADS_APP_SECRET)
    identity = await client.graph_get(
        "me",
        params={"fields": "id,name"},
        operation="discover_identity",
        policy=IntegrationRequestPolicy.READ,
    )
    if not isinstance(identity.get("id"), str) or not identity["id"].strip():
        raise IntegrationValidationError(
            "Meta Ads could not identify the system user. Generate a System User access token "
            "for your agency's Meta app and replace this connection's token.",
            provider_key="meta_ads",
            operation="discover_identity",
        )
    permissions, permissions_truncated = await client.graph_get_paged(
        "me/permissions",
        operation="discover_permissions",
        policy=IntegrationRequestPolicy.READ,
    )
    granted = sorted(
        {
            row["permission"]
            for row in permissions
            if row.get("status") == "granted" and isinstance(row.get("permission"), str)
        }
    )
    accounts, truncated = await client.graph_get_paged(
        "me/adaccounts",
        params={"fields": _ACCOUNT_FIELDS, "limit": 100},
        operation="discover_ad_accounts",
        policy=IntegrationRequestPolicy.READ,
        max_pages=20,
    )
    resources: dict[str, DiscoveredIntegrationResource] = {}
    closed: set[str] = set()
    for account in accounts:
        account_id = _account_id(account)
        resource = _resource(
            account, account_id, granted, permissions_complete=not permissions_truncated
        )
        if resource is None:
            closed.add(account_id)
            resources.pop(account_id, None)
            continue
        if account_id in closed:
            continue
        previous = resources.get(resource.external_id)
        if previous is not None:
            resource = replace(previous, writable=previous.writable and resource.writable)
        resources[resource.external_id] = resource
    return IntegrationDiscoveryResult(
        resources=tuple(sorted(resources.values(), key=lambda item: item.display_name.casefold())),
        degraded_reason="page_cap" if truncated or permissions_truncated else None,
    )


def _resource(
    account: dict[str, Any],
    account_id: str,
    granted: list[str],
    *,
    permissions_complete: bool,
) -> DiscoveredIntegrationResource | None:
    status_code = account.get("account_status")
    if type(status_code) is not int:
        status_code = None
    if status_code in (100, 101):
        return None
    raw_tasks = account.get("user_tasks")
    tasks = (
        sorted({task for task in raw_tasks if isinstance(task, str)})
        if isinstance(raw_tasks, list)
        else []
    )
    business = account.get("business")
    business = business if isinstance(business, dict) else {}
    return DiscoveredIntegrationResource(
        resource_type="meta_ads_ad_account",
        external_id=account_id,
        display_name=(metadata_str(account.get("name")) or "").strip()
        or f"Ad account {account_id}",
        writable=(
            permissions_complete
            and status_code == 1
            and "ads_management" in granted
            and bool({"MANAGE", "ADVERTISE"}.intersection(tasks))
        ),
        permissions_metadata={
            "currency": (metadata_str(account.get("currency")) or "").strip(),
            "timezone_name": (metadata_str(account.get("timezone_name")) or "").strip(),
            "account_status": _ACCOUNT_STATUSES.get(status_code, "UNKNOWN"),
            "business_id": (metadata_str(business.get("id")) or "").strip(),
            "business_name": (metadata_str(business.get("name")) or "").strip(),
            "tasks": tasks,
            "token_permissions": granted,
        },
    )


def _account_id(account: dict[str, Any]) -> str:
    account_id = normalize_ad_account_id(account.get("account_id", account.get("id", "")))
    if account.get("id") and normalize_ad_account_id(account["id"]) != account_id:
        raise IntegrationValidationError(
            "Meta Ads returned conflicting ad account IDs.",
            provider_key="meta_ads",
            operation="discover_ad_accounts",
        )
    return account_id
