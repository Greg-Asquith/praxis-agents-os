# apps/api/services/integrations/microsoft_graph/people.py

"""Provider-neutral Microsoft Graph people search."""

import re
from typing import Any

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from .client import MicrosoftGraphClient

PersonResult = tuple[str, str, str, str]


async def search_people(
    client: MicrosoftGraphClient,
    *,
    query: str,
    limit: int,
) -> list[PersonResult]:
    """Search the delegated user's relevant people with a provider-side bound."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("Microsoft Graph people search query must not be blank")
    bounded_limit = max(1, min(limit, 25))
    payload = await client.post(
        "/search/query",
        operation="search_people",
        policy=IntegrationRequestPolicy.READ,
        json={
            "requests": [
                {
                    "entityTypes": ["person"],
                    "query": {"queryString": normalized_query},
                    "size": bounded_limit,
                }
            ]
        },
    )
    resources = _person_resources(payload)
    return [
        (
            _string(resource.get("displayName")),
            address,
            _string(resource.get("jobTitle")),
            _string(resource.get("department")),
        )
        for resource in resources[:bounded_limit]
        if (address := _person_address(resource))
    ]


def _person_resources(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
        raise _search_response_error()
    resources: list[dict[str, Any]] = []
    for response in payload["value"]:
        if not isinstance(response, dict):
            continue
        containers = response.get("hitsContainers")
        if not isinstance(containers, list):
            continue
        for container in containers:
            if not isinstance(container, dict) or not isinstance(container.get("hits"), list):
                continue
            resources.extend(
                hit["resource"]
                for hit in container["hits"]
                if isinstance(hit, dict) and isinstance(hit.get("resource"), dict)
            )
    return resources


def _person_address(resource: dict[str, Any]) -> str:
    values = resource.get("emailAddresses")
    addresses = (
        [_string(value.get("address")) for value in values if isinstance(value, dict)]
        if isinstance(values, list)
        else []
    )
    addresses.append(_string(resource.get("userPrincipalName")))
    return next(
        (address for address in addresses if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address)),
        "",
    )


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _search_response_error() -> IntegrationValidationError:
    return IntegrationValidationError(
        "Microsoft Graph returned an invalid people search response",
        provider_key="microsoft_graph",
        operation="search_people",
    )
