# apps/api/integrations/google_ads/entity_resolvers/label.py

"""Google Ads label lookup for runtime entity selectors."""

from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.operations.count_label_associations import (
    count_label_associations,
)
from integrations.google_ads.operations.list_labels import list_labels
from integrations.google_ads.references import (
    GoogleAdsLabelReference,
    label_reference_from_row,
)
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
)

from .utils import group_scoped_references, search_scoped_entities


def _choice(entry, label: Mapping[str, Any]) -> EntityChoice | None:
    reference = label_reference_from_row(
        entry.external_id,
        label,
        scope_label=entry.display_name,
        association_counts=label.get("associationCounts"),
    )
    return EntityChoice.from_reference(reference, icon="google_ads") if reference else None


async def _query(
    ctx,
    entry,
    *,
    label_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
) -> list[Mapping[str, Any]]:
    client = await google_ads_client_for_principal(
        ctx.db,
        actor=ctx.actor,
        workspace=ctx.workspace,
        entry=entry,
    )
    labels = await list_labels(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        label_ids=label_ids,
        search=search,
        minimum_id=minimum_id,
        minimum_id_inclusive=minimum_id_inclusive,
        limit=limit,
    )
    ids = [str(label.get("id", "")) for label in labels]
    if not ids or any(not label_id.isdigit() for label_id in ids):
        return labels
    counts = await count_label_associations(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        label_ids=ids,
    )
    return [{**label, "associationCounts": counts.get(str(label["id"]))} for label in labels]


async def search_google_ads_labels(ctx, search, _dependent_args, page_size, cursor):
    normalized_search = search.strip()

    async def query_entry(entry, minimum_id, _minimum_secondary_id, inclusive, limit):
        return await _query(
            ctx,
            entry,
            search=normalized_search or None,
            minimum_id=minimum_id,
            minimum_id_inclusive=inclusive,
            limit=limit,
        )

    return await search_scoped_entities(
        ctx,
        GOOGLE_ADS_BINDING,
        search=normalized_search,
        page_size=page_size,
        cursor=cursor,
        query_entry=query_entry,
        choice_for_row=_choice,
    )


async def resolve_google_ads_labels(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(ctx, GOOGLE_ADS_BINDING, values, GoogleAdsLabelReference)
    for entry, references in grouped:
        ids = [reference.label_id for reference in references]
        labels = await _query(ctx, entry, label_ids=ids, limit=len(ids))
        choices.extend(choice for label in labels if (choice := _choice(entry, label)) is not None)
    return tuple(choices)


GOOGLE_ADS_LABEL_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_label",
    reference_type=GoogleAdsLabelReference,
    search=search_google_ads_labels,
    resolve=resolve_google_ads_labels,
    max_page_size=25,
    requires_active_context=True,
    provider_key="google_ads",
)
