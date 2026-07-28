# apps/api/integrations/google_ads/discover_resources.py

"""Discover accessible Google Ads customers and MCC hierarchy metadata."""

from core.exceptions.integration import (
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationValidationError,
)
from services.integrations.credentials import (
    GoogleServiceAccountTokenProvider,
    parse_google_service_account_json,
)
from services.integrations.plugin import DiscoveredIntegrationResource

from .client import GoogleAdsClient, normalize_customer_id
from .operations.utils import stream_rows
from .settings import google_ads_settings

_HIERARCHY_QUERY = """
SELECT
  customer_client.client_customer,
  customer_client.level,
  customer_client.manager,
  customer_client.descriptive_name,
  customer_client.currency_code,
  customer_client.status
FROM customer_client
WHERE customer_client.level <= 1
""".strip()
_WRITE_ROLES = frozenset({"ADMIN", "STANDARD"})
GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"


async def discover_resources(
    credential_value: str,
    principal_label: str | None = None,
) -> tuple[DiscoveredIntegrationResource, ...]:
    """Resolve either OAuth or service-account material into one client seam."""
    if credential_value.lstrip().startswith("{"):
        credentials = parse_google_service_account_json(
            credential_value,
            provider_key="google_ads",
        )
        token_provider = GoogleServiceAccountTokenProvider(
            credentials,
            provider_key="google_ads",
            scope=GOOGLE_ADS_SCOPE,
        )
        access_token = token_provider.access_token
        principal_email = credentials.client_email
    else:

        async def access_token(_force: bool) -> str:
            return credential_value

        principal_email = principal_label
    developer_token = google_ads_settings.GOOGLE_ADS_DEVELOPER_TOKEN
    if developer_token is None or not developer_token.get_secret_value().strip():
        raise IntegrationValidationError(
            "Google Ads provider operations are not configured",
            provider_key="google_ads",
            operation="discover_resources",
        )
    return await discover_google_ads_resources(
        GoogleAdsClient(access_token, developer_token=developer_token),
        principal_email=principal_email,
    )


async def discover_google_ads_resources(
    client: GoogleAdsClient,
    *,
    principal_email: str | None,
) -> tuple[DiscoveredIntegrationResource, ...]:
    payload = await client.get(
        "customers:listAccessibleCustomers", operation="list_accessible_customers"
    )
    names = payload.get("resourceNames", []) if isinstance(payload, dict) else []
    roots = tuple(
        dict.fromkeys(
            normalize_customer_id(str(name).rsplit("/", 1)[-1])
            for name in names
            if str(name).strip()
        )
    )
    discovered: dict[str, DiscoveredIntegrationResource] = {}
    for root_id in roots:
        root_role = await _access_role(
            client,
            customer_id=root_id,
            login_customer_id=root_id,
            principal_email=principal_email,
        )
        pending_managers = [(root_id, 0)]
        queried_managers: set[str] = set()
        while pending_managers:
            query_customer_id, query_level = pending_managers.pop(0)
            if query_customer_id in queried_managers:
                continue
            queried_managers.add(query_customer_id)
            hierarchy = await client.post(
                f"customers/{query_customer_id}/googleAds:searchStream",
                operation="discover_customer_hierarchy",
                login_customer_id=root_id,
                json={"query": _HIERARCHY_QUERY},
            )
            for row in stream_rows(hierarchy):
                customer = row.get("customerClient")
                if not isinstance(customer, dict):
                    continue
                external_id = normalize_customer_id(str(customer.get("clientCustomer", "")))
                try:
                    relative_level = int(customer.get("level", 0))
                except (TypeError, ValueError):
                    relative_level = 0
                if relative_level not in {0, 1}:
                    continue
                if query_customer_id != root_id and external_id == query_customer_id:
                    continue
                manager = bool(customer.get("manager", False))
                level = query_level + relative_level
                if manager and relative_level == 1 and external_id not in queried_managers:
                    pending_managers.append((external_id, level))
                parent_external_id = None if relative_level == 0 else query_customer_id
                metadata = {
                    "manager": manager,
                    "parent_external_id": parent_external_id,
                    "level": level,
                    "currency_code": str(customer.get("currencyCode", "")),
                    "descriptive_name": str(customer.get("descriptiveName", "")),
                    "status": str(customer.get("status", "")),
                    "login_customer_id": root_id,
                    "access_role": root_role or "UNKNOWN",
                }
                candidate = DiscoveredIntegrationResource(
                    resource_type="google_ads_account",
                    external_id=external_id,
                    display_name=str(customer.get("descriptiveName", "")).strip() or external_id,
                    parent_external_id=parent_external_id,
                    writable=not manager and root_role in _WRITE_ROLES,
                    permissions_metadata=metadata,
                )
                existing = discovered.get(external_id)
                if existing is None or _prefer_candidate(candidate, existing):
                    discovered[external_id] = candidate
    return tuple(discovered.values())


async def _access_role(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    principal_email: str | None,
) -> str | None:
    if not principal_email:
        return None
    escaped_email = principal_email.replace("\\", "\\\\").replace("'", "\\'")
    query = (
        "SELECT customer_user_access.email_address, customer_user_access.access_role "  # noqa: S608 -- GAQL has no bind parameters; literal is escaped below.
        "FROM customer_user_access "
        f"WHERE customer_user_access.email_address = '{escaped_email}' LIMIT 1"
    )
    try:
        payload = await client.post(
            f"customers/{customer_id}/googleAds:searchStream",
            operation="discover_customer_access_role",
            login_customer_id=login_customer_id,
            json={"query": query},
        )
    except (
        IntegrationNotFoundError,
        IntegrationPermissionError,
        IntegrationValidationError,
    ):
        return None
    for row in stream_rows(payload):
        access = row.get("customerUserAccess")
        if isinstance(access, dict):
            return str(access.get("accessRole", "")).upper() or None
    return None


def _prefer_candidate(
    candidate: DiscoveredIntegrationResource,
    existing: DiscoveredIntegrationResource,
) -> bool:
    if candidate.writable != existing.writable:
        return candidate.writable
    candidate_level = int((candidate.permissions_metadata or {}).get("level", 0))
    existing_level = int((existing.permissions_metadata or {}).get("level", 0))
    return candidate_level < existing_level
