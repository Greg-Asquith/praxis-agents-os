"""BigQuery manifest, REST client, and dataset-discovery contracts."""

from typing import Any

import httpx2
import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.bigquery import PROVIDER
from integrations.bigquery.client import BigQueryClient
from integrations.bigquery.discover_resources import discover_bigquery_resources
from integrations.bigquery.sync_table_schemas import SYNC_TABLE_SCHEMAS_KIND
from services.integrations.credentials import parse_google_service_account_json
from services.integrations.loader import _validate_plugin


def test_manifest_declares_read_only_workspace_dataset_provider() -> None:
    manifest = PROVIDER.manifest

    assert manifest.provider_key == "bigquery"
    assert manifest.display_name == "Google BigQuery"
    assert manifest.auth_modes == ("service_account",)
    assert manifest.owner_scope == "workspace"
    assert manifest.resource_types == ("bigquery_dataset",)
    assert manifest.requires_discovery is True
    assert manifest.capability_flags == frozenset({"read"})
    assert PROVIDER.metadata_sync_job_kind == SYNC_TABLE_SCHEMAS_KIND
    assert PROVIDER.tool_definitions == ()
    _validate_plugin(PROVIDER, expected_key="bigquery")


def test_google_service_account_validation_attributes_the_provider() -> None:
    with pytest.raises(IntegrationValidationError) as exc_info:
        parse_google_service_account_json("not-json", provider_key="bigquery")

    assert exc_info.value.provider_key == "bigquery"
    assert exc_info.value.operation == "validate_service_account"


async def test_client_refreshes_once_after_an_auth_failure() -> None:
    tokens = iter(("expired-token", "fresh-token"))
    force_values: list[bool] = []
    seen_authorization: list[str] = []

    async def access_token(force: bool) -> str:
        force_values.append(force)
        return next(tokens)

    def handler(request: httpx2.Request) -> httpx2.Response:
        authorization = request.headers["Authorization"]
        seen_authorization.append(authorization)
        status = 401 if authorization == "Bearer expired-token" else 200
        return httpx2.Response(status, json={"projects": []}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        result = await BigQueryClient(access_token, client=http_client).get(
            "projects",
            operation="list_projects",
            params={"maxResults": 1000},
        )

    assert result == {"projects": []}
    assert force_values == [False, True]
    assert seen_authorization == ["Bearer expired-token", "Bearer fresh-token"]


async def test_discovery_pages_projects_and_datasets_into_read_only_resources() -> None:
    client = _DiscoveryClient()

    resources = await discover_bigquery_resources(client)

    assert [resource.external_id for resource in resources] == [
        "analytics-prod.marketing",
        "analytics-prod.finance",
    ]
    marketing, finance = resources
    assert marketing.display_name == "Marketing reporting"
    assert marketing.resource_type == "bigquery_dataset"
    assert marketing.writable is False
    assert marketing.permissions_metadata == {
        "project_id": "analytics-prod",
        "dataset_id": "marketing",
        "location": "EU",
    }
    assert finance.display_name == "analytics-prod.finance"
    assert finance.permissions_metadata == {
        "project_id": "analytics-prod",
        "dataset_id": "finance",
        "location": "US",
    }
    assert client.calls == [
        ("projects", {"maxResults": 1000}),
        ("projects/analytics-prod/datasets", {"maxResults": 1000}),
        (
            "projects/analytics-prod/datasets",
            {"maxResults": 1000, "pageToken": "datasets-page-2"},
        ),
        ("projects", {"maxResults": 1000, "pageToken": "projects-page-2"}),
        ("projects/empty-project/datasets", {"maxResults": 1000}),
    ]


class _DiscoveryClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._responses: dict[tuple[str, str | None], dict[str, Any]] = {
            ("projects", None): {
                "projects": [
                    {"projectReference": {"projectId": "analytics-prod"}},
                    {"projectReference": {}},
                ],
                "nextPageToken": "projects-page-2",
            },
            ("projects", "projects-page-2"): {
                "projects": [{"projectReference": {"projectId": "empty-project"}}],
                "nextPageToken": "projects-page-2",
            },
            ("projects/analytics-prod/datasets", None): {
                "datasets": [
                    {
                        "datasetReference": {
                            "projectId": "analytics-prod",
                            "datasetId": "marketing",
                        },
                        "friendlyName": "Marketing reporting",
                        "location": "EU",
                    },
                    {"datasetReference": {"projectId": "analytics-prod"}},
                ],
                "nextPageToken": "datasets-page-2",
            },
            ("projects/analytics-prod/datasets", "datasets-page-2"): {
                "datasets": [
                    {
                        "datasetReference": {
                            "projectId": "analytics-prod",
                            "datasetId": "finance",
                        },
                        "location": "US",
                    }
                ]
            },
            ("projects/empty-project/datasets", None): {},
        }

    async def get(
        self,
        path: str,
        *,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        assert operation in {"list_projects", "list_datasets"}
        resolved_params = params or {}
        self.calls.append((path, resolved_params))
        return self._responses[(path, resolved_params.get("pageToken"))]
