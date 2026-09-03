# apps/api/integrations/google_ads/entity_resolves/keyword.py

"""Google Ads positive-keyword lookup for shared runtime entity selectors."""

from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.operations.list_positive_keywords import list_positive_keywords
from integrations.google_ads.references import (
    GoogleAdsKeywordReference,
    positive_keyword_reference_from_row,
)
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.entity_references import EntityChoice, EntityResolverDefinition

from .utils import group_scoped_references, search_scoped_entities

_MAX_KEYWORD_REFERENCES = 500
_QUERY_BATCH_SIZE = 50


def _choice(entry, row: Mapping[str, Any]) -> EntityChoice | None:
    reference = positive_keyword_reference_from_row(entry.external_id, row)
    return EntityChoice.from_reference(reference, icon="google_ads") if reference else None


async def _query(
    ctx,
    entry,
    *,
    criterion_ids: Sequence[str] = (),
    ad_group_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_ad_group_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
) -> list[Mapping[str, Any]]:
    client = await google_ads_client_for_principal(
        ctx.db,
        actor=ctx.actor,
        workspace=ctx.workspace,
        entry=entry,
    )
    return await list_positive_keywords(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        criterion_ids=criterion_ids,
        ad_group_ids=ad_group_ids,
        search=search,
        minimum_id=minimum_id,
        minimum_ad_group_id=minimum_ad_group_id,
        minimum_id_inclusive=minimum_id_inclusive,
        limit=limit,
    )


async def search_google_ads_keywords(ctx, search, _dependent_args, page_size, cursor):
    normalized_search = search.strip()

    async def query_entry(entry, minimum_id, minimum_ad_group_id, inclusive, limit):
        return await _query(
            ctx,
            entry,
            search=normalized_search or None,
            minimum_id=minimum_id,
            minimum_ad_group_id=minimum_ad_group_id,
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


async def resolve_google_ads_keywords(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(
        ctx,
        GOOGLE_ADS_BINDING,
        values,
        GoogleAdsKeywordReference,
        max_references=_MAX_KEYWORD_REFERENCES,
    )
    for entry, references in grouped:
        for start in range(0, len(references), _QUERY_BATCH_SIZE):
            batch = references[start : start + _QUERY_BATCH_SIZE]
            expected = {(reference.ad_group_id, reference.criterion_id) for reference in batch}
            criterion_ids = sorted({reference.criterion_id for reference in batch})
            ad_group_ids = sorted({reference.ad_group_id for reference in batch})
            rows = await _query(
                ctx,
                entry,
                criterion_ids=criterion_ids,
                ad_group_ids=ad_group_ids,
                limit=len(criterion_ids) * len(ad_group_ids),
            )
            for row in rows:
                reference = positive_keyword_reference_from_row(entry.external_id, row)
                if (
                    reference is None
                    or (reference.ad_group_id, reference.criterion_id) not in expected
                ):
                    continue
                choices.append(EntityChoice.from_reference(reference, icon="google_ads"))
    return tuple(choices)


GOOGLE_ADS_KEYWORD_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_keyword",
    reference_type=GoogleAdsKeywordReference,
    search=search_google_ads_keywords,
    resolve=resolve_google_ads_keywords,
    max_page_size=25,
    max_exact_values=_MAX_KEYWORD_REFERENCES,
    requires_active_context=True,
    provider_key="google_ads",
)
