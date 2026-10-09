# apps/api/integrations/meta_ads/operations/create_objects.py

"""Creation rules for Meta ads.

Every create is checked with a dry run first, sent once, and settled by a name lookup
when Meta's reply is lost; it's never sent again. Creates are read back afterwards,
in batches, by the caller.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from core.exceptions.integration import (
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient, ad_account_path
from ..throttle import ensure_account_available
from ..tools.schemas.objects import UNDELETED_AD_STATUSES
from .paging import read_pages

type MetaAdsCreateEdge = Literal["ads"]
type MetaCreateStatus = Literal["applied", "failed", "unverified"]

# Allows for clock differences between this server and Meta when matching a lost create.
_CLOCK_MARGIN = timedelta(minutes=5)
_MAX_MATCHES = 5
_UNDELETED_FILTER = {"field": "effective_status", "operator": "IN", "value": UNDELETED_AD_STATUSES}
_DRY_RUN_UNCONFIRMED = "Meta Ads didn't confirm this could be created."
_UNCONFIRMED = (
    "Meta Ads didn't confirm this was created. Check Ads Manager before creating it again."
)


@dataclass(frozen=True, slots=True)
class MetaCreateResult:
    """What one create proved; failed and unverified outcomes carry diagnostics."""

    status: MetaCreateStatus
    object_id: str | None = None
    # True when an unclear reply was settled by finding the object by name.
    recovered: bool = False
    error_code: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class MetaCreateLookup:
    """How to find a create whose reply was lost: same name, same parent, made since `since`."""

    name: str
    parent_field: Literal["campaign.id", "adset.id"]
    parent_id: str
    since: datetime


async def validate_create(
    client: MetaAdsClient,
    *,
    account_id: str,
    edge: MetaAdsCreateEdge,
    data: Mapping[str, str],
    operation: str,
) -> str | None:
    """Asks Meta to check one create without making it.

    Returns:
        Meta's reason when it rejects the create or doesn't confirm it, otherwise None.
    """
    ensure_account_available(account_id, operation=operation)
    try:
        payload = await client.graph_post(
            f"{ad_account_path(account_id)}/{edge}",
            data={**data, "execution_options": json.dumps(["validate_only"])},
            # The client keeps Meta's reason for rejections of operations named validate_*.
            operation=f"validate_{operation}",
            # A dry run creates nothing, so retrying it is safe.
            policy=IntegrationRequestPolicy.IDEMPOTENT_WRITE,
            usage_account_id=account_id,
        )
    except IntegrationValidationError as exc:
        return exc.user_message
    return None if payload == {"success": True} else _DRY_RUN_UNCONFIRMED


async def create_object(
    client: MetaAdsClient,
    *,
    account_id: str,
    edge: MetaAdsCreateEdge,
    data: Mapping[str, str],
    operation: str,
    lookup: MetaCreateLookup,
) -> MetaCreateResult:
    """Sends one create once; an unclear reply is settled by one bounded lookup.

    A rejection is a failure. A lost or unreadable reply counts as created only when
    exactly one object with the name exists under the parent; otherwise it's unverified.
    """
    try:
        ensure_account_available(account_id, operation=operation)
        payload = await client.graph_post(
            f"{ad_account_path(account_id)}/{edge}",
            data=dict(data),
            operation=operation,
            policy=IntegrationRequestPolicy.MUTATION,
            usage_account_id=account_id,
        )
    except IntegrationError as exc:
        if exc.failure_disposition in (
            IntegrationFailureDisposition.REJECTED,
            IntegrationFailureDisposition.NOT_DISPATCHED,
        ):
            return MetaCreateResult(
                "failed",
                error_code=(exc.error_code or exc.__class__.__name__)[:100],
                message=" ".join(exc.user_message.split())[:1000] or _UNCONFIRMED,
            )
        return await _reconcile(client, account_id, edge, operation, lookup)
    object_id = payload.get("id")
    if not _digits(object_id):
        return await _reconcile(client, account_id, edge, operation, lookup)
    return MetaCreateResult("applied", object_id)


async def _find_created(
    client: MetaAdsClient,
    *,
    account_id: str,
    edge: MetaAdsCreateEdge,
    lookup: MetaCreateLookup,
    operation: str,
) -> list[str]:
    """Lists objects under the parent with exactly the name, created since the attempt."""
    filters = [
        _UNDELETED_FILTER,
        {"field": "name", "operator": "CONTAIN", "value": lookup.name},
        {"field": lookup.parent_field, "operator": "IN", "value": [lookup.parent_id]},
    ]
    rows, _more = await read_pages(
        client,
        path=f"{ad_account_path(account_id)}/{edge}",
        account_id=account_id,
        params={"fields": "id,name,created_time", "filtering": json.dumps(filters)},
        limit=_MAX_MATCHES,
        budget=ReportResultBudget("meta_ads", operation),
        operation=operation,
        include=lambda row: row.get("name") == lookup.name and _since(row, lookup.since),
    )
    return [str(row["id"]) for row in rows if _digits(row.get("id"))]


async def read_created(
    client: MetaAdsClient,
    *,
    account_id: str,
    edge: MetaAdsCreateEdge,
    object_ids: Sequence[str],
    fields: str,
    operation: str,
) -> dict[str, dict[str, Any]]:
    """Reads new objects through the account's own edge, 50 at a time, in any status."""
    ids = sorted(set(object_ids))
    found: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), 50):
        chunk = ids[start : start + 50]
        filters = [_UNDELETED_FILTER, {"field": "id", "operator": "IN", "value": chunk}]
        rows, _more = await read_pages(
            client,
            path=f"{ad_account_path(account_id)}/{edge}",
            account_id=account_id,
            params={"fields": fields, "filtering": json.dumps(filters)},
            limit=len(chunk),
            budget=ReportResultBudget("meta_ads", operation),
            operation=operation,
        )
        found.update((str(row["id"]), row) for row in rows if str(row.get("id")) in chunk)
    return found


async def _reconcile(
    client: MetaAdsClient,
    account_id: str,
    edge: MetaAdsCreateEdge,
    operation: str,
    lookup: MetaCreateLookup,
) -> MetaCreateResult:
    try:
        matches = await _find_created(
            client, account_id=account_id, edge=edge, lookup=lookup, operation=operation
        )
    except IntegrationError:
        matches = []
    if len(matches) == 1:
        return MetaCreateResult("applied", matches[0], recovered=True)
    return MetaCreateResult("unverified", error_code="CREATE_NOT_CONFIRMED", message=_UNCONFIRMED)


def _digits(value: Any) -> bool:
    return isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 128


def _since(row: Mapping[str, Any], since: datetime) -> bool:
    value = row.get("created_time")
    try:
        created = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return False
    return created is not None and created.tzinfo is not None and created >= since - _CLOCK_MARGIN
