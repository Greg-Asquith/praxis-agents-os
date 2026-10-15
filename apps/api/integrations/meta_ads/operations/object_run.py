# apps/api/integrations/meta_ads/operations/object_run.py

"""What creating one campaign or ad set proved: one send, a read-back, and its ledger."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from core.exceptions.integration import IntegrationError

from ..client import MetaAdsClient
from ..tools.schemas.objects import MetaAdsObject
from .ad_rows import ad_effect
from .create_objects import MetaAdsCreateEdge, MetaCreateLookup, MetaCreateResult, create_object
from .list_objects import read_objects_by_id
from .mutations import MetaAdsMutationLedger, MetaAdsMutationParent


@dataclass
class ObjectRun:
    """What the one create proved."""

    fields: dict[str, str]
    outcome: MetaCreateResult | None = None
    # Set once the create has been handed to Meta, so an interruption is unverified.
    sending: bool = False
    skip_code: str | None = None
    skip_message: str | None = None
    read: dict[str, Any] | None = None
    created: MetaAdsObject | None = None

    action: ClassVar[str]
    edge: ClassVar[MetaAdsCreateEdge]
    object_type: ClassVar[Literal["campaign", "adset"]]
    noun: ClassVar[str]
    key: ClassVar[str]

    @property
    def enabled(self) -> frozenset[str]:
        return frozenset()

    def ledger(self) -> MetaAdsMutationLedger:
        return MetaAdsMutationLedger(
            action=self.action,
            parents=(
                MetaAdsMutationParent(
                    identity=(("key", self.key),), decision="submit", effects=(ad_effect(self),)
                ),
            ),
        )


async def create_and_read_back[Run: ObjectRun](
    client: MetaAdsClient,
    run: Run,
    *,
    account_id: str,
    currency: str,
    body: Mapping[str, str],
    operation: str,
    lookup: MetaCreateLookup,
) -> Run:
    """Sends the create once, settles a lost reply by name, then reads the object back."""
    try:
        run.sending = True
        run.outcome = await create_object(
            client,
            account_id=account_id,
            edge=run.edge,
            data=body,
            operation=operation,
            lookup=lookup,
        )
        if (created_id := run.outcome.object_id) and run.outcome.status == "applied":
            await _read_back(client, account_id, currency, created_id, run)
    except (asyncio.CancelledError, Exception) as exc:
        # Unverified once the create was sent.
        exc.ledger = run.ledger()
        raise
    return run


async def _read_back(
    client: MetaAdsClient, account_id: str, currency: str, object_id: str, run: ObjectRun
) -> None:
    try:
        found = await read_objects_by_id(
            client,
            account_id=account_id,
            object_type=run.object_type,
            object_ids=[object_id],
            currency=currency,
        )
    except IntegrationError:
        return
    if item := found.get(object_id):
        run.created = item
        run.read = {"effective_status": item.effective_status}


def readback_message(run: ObjectRun) -> str | None:
    effect = ad_effect(run)
    if effect.outcome == "applied" and run.read is None:
        return f"Meta Ads created this {run.noun}, but it couldn't be read back."
    return effect.message
