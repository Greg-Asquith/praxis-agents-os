# apps/api/integrations/bigquery/discover_resources.py

"""Discover BigQuery datasets visible to a Google service account."""

from collections.abc import AsyncIterator
from typing import Any, Protocol
from urllib.parse import quote

from services.integrations.credentials import (
    GoogleServiceAccountTokenProvider,
    parse_google_service_account_json,
)
from services.integrations.plugin import DiscoveredIntegrationResource

from .client import BigQueryClient
from .settings import BIGQUERY_DISCOVERY_PAGE_SIZE

BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"


class BigQueryDiscoveryClient(Protocol):
    async def get(
        self,
        path: str,
        *,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> Any: ...


async def discover_resources(
    credential_value: str,
    _principal_label: str | None = None,
) -> tuple[DiscoveredIntegrationResource, ...]:
    credentials = parse_google_service_account_json(
        credential_value,
        provider_key="bigquery",
    )
    token_provider = GoogleServiceAccountTokenProvider(
        credentials,
        provider_key="bigquery",
        scope=BIGQUERY_SCOPE,
    )
    return await discover_bigquery_resources(BigQueryClient(token_provider.access_token))


async def discover_bigquery_resources(
    client: BigQueryDiscoveryClient,
) -> tuple[DiscoveredIntegrationResource, ...]:
    resources: dict[str, DiscoveredIntegrationResource] = {}
    async for project in _pages(client, path="projects", collection_key="projects"):
        reference = project.get("projectReference")
        if not isinstance(reference, dict):
            continue
        project_id = str(reference.get("projectId", "")).strip()
        if not project_id:
            continue
        path = f"projects/{quote(project_id, safe='')}/datasets"
        async for dataset in _pages(client, path=path, collection_key="datasets"):
            resource = _dataset_resource(dataset, fallback_project_id=project_id)
            if resource is not None:
                resources[resource.external_id] = resource
    return tuple(resources.values())


async def _pages(
    client: BigQueryDiscoveryClient,
    *,
    path: str,
    collection_key: str,
) -> AsyncIterator[dict[str, Any]]:
    page_token: str | None = None
    seen_tokens: set[str] = set()
    while True:
        params: dict[str, Any] = {"maxResults": BIGQUERY_DISCOVERY_PAGE_SIZE}
        if page_token is not None:
            params["pageToken"] = page_token
        payload = await client.get(
            path,
            operation=f"list_{collection_key}",
            params=params,
        )
        items = payload.get(collection_key) if isinstance(payload, dict) else None
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    yield item
        next_token = (
            str(payload.get("nextPageToken", "")).strip() if isinstance(payload, dict) else ""
        )
        if not next_token or next_token in seen_tokens:
            return
        seen_tokens.add(next_token)
        page_token = next_token


def _dataset_resource(
    payload: dict[str, Any],
    *,
    fallback_project_id: str,
) -> DiscoveredIntegrationResource | None:
    reference = payload.get("datasetReference")
    if not isinstance(reference, dict):
        return None
    project_id = str(reference.get("projectId", "")).strip() or fallback_project_id
    dataset_id = str(reference.get("datasetId", "")).strip()
    if not project_id or not dataset_id:
        return None
    external_id = f"{project_id}.{dataset_id}"
    return DiscoveredIntegrationResource(
        resource_type="bigquery_dataset",
        external_id=external_id,
        display_name=str(payload.get("friendlyName", "")).strip() or external_id,
        writable=False,
        permissions_metadata={
            "project_id": project_id,
            "dataset_id": dataset_id,
            "location": str(payload.get("location", "")).strip(),
        },
    )
