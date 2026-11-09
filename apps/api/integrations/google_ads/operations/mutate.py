# apps/api/integrations/google_ads/operations/mutate.py

"""One `googleAds:mutate` request across resource types, and its per-operation results."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import grouped_partial_failure_errors

# At most this many operations go in one request; Google's limit is 10,000.
MAX_MUTATE_OPERATIONS = 5_000


@dataclass(frozen=True, slots=True)
class MutateOperation:
    """One operation for a resource type, such as `campaign` or `adGroupCriterion`."""

    resource: str
    body: Mapping[str, Any]

    def payload(self) -> dict[str, Any]:
        return {f"{self.resource}Operation": dict(self.body)}


@dataclass(frozen=True, slots=True)
class MutateResponse:
    """Each operation's returned resource name and Google's diagnostics, by operation index."""

    # None when the results can't be lined up with the operations sent.
    results: list[dict[str, str]] | None
    indexed_errors: dict[int, dict[str, str]]
    unattributed_errors: list[dict[str, str]]


async def google_ads_mutate(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    operations: Sequence[MutateOperation],
    partial_failure: bool,
    validate_only: bool,
    operation: str,
) -> MutateResponse:
    """Sends operations in one request, or checks them without making changes.

    Raises:
        IntegrationError: When Google rejects the whole request or the reply is unclear.
    """
    if not operations or len(operations) > MAX_MUTATE_OPERATIONS:
        raise ValueError("Google Ads mutate requests need between 1 and 5,000 operations")
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:mutate",
        operation=f"validate_{operation}" if validate_only else operation,
        # A dry run changes nothing, so retrying it is safe.
        policy=(
            IntegrationRequestPolicy.IDEMPOTENT_WRITE
            if validate_only
            else IntegrationRequestPolicy.MUTATION
        ),
        login_customer_id=login_customer_id,
        json={
            "mutateOperations": [item.payload() for item in operations],
            "partialFailure": partial_failure,
            "validateOnly": validate_only,
        },
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        list(range(len(operations))),
        value_to_error_fields=lambda _index: {},
        unattributed_error_fields={},
        default_message="Google Ads rejected this change",
    )
    return MutateResponse(
        results=_results(payload, operations),
        indexed_errors=indexed_errors,
        unattributed_errors=unattributed_errors,
    )


def _results(payload: Any, operations: Sequence[MutateOperation]) -> list[dict[str, str]] | None:
    responses = payload.get("mutateOperationResponses") if isinstance(payload, dict) else None
    if not isinstance(responses, list) or len(responses) != len(operations):
        return None
    results: list[dict[str, str]] = []
    for response, item in zip(responses, operations, strict=True):
        result = response.get(f"{item.resource}Result") if isinstance(response, dict) else None
        name = result.get("resourceName") if isinstance(result, dict) else None
        # A failed operation's slot is empty under partial failure.
        results.append({"resourceName": name} if isinstance(name, str) and name else {})
    return results
