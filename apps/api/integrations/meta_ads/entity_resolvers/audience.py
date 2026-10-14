# apps/api/integrations/meta_ads/entity_resolvers/audience.py

"""Custom and lookalike audience lookup for shared runtime entity selectors."""

from collections.abc import Sequence

from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.entity_references import EntityResolverContext, EntityResolverDefinition
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient
from ..operations.list_assets import read_audience_references
from ..references import MetaAdsAudienceReference
from .utils import asset_read_args, resolve_assets, search_assets


async def _read(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    budget: ReportResultBudget,
    references: Sequence[MetaAdsAudienceReference] = (),
) -> list[MetaAdsAudienceReference]:
    # Exact lookups scan the account's own edge, so audiences past the first 200 still resolve.
    audience_ids = sorted({reference.audience_id for reference in references})
    audiences, _more = await read_audience_references(
        client, **asset_read_args(entry, budget), audience_ids=audience_ids
    )
    return audiences


async def search_meta_ads_audiences(
    ctx: EntityResolverContext, search, _dependent_args, page_size, cursor
):
    return await search_assets(ctx, search, page_size=page_size, cursor=cursor, read=_read)


async def resolve_meta_ads_audiences(ctx: EntityResolverContext, values, _dependent_args):
    return await resolve_assets(ctx, values, reference_type=MetaAdsAudienceReference, read=_read)


META_ADS_AUDIENCE_RESOLVER = EntityResolverDefinition(
    entity_kind="meta_ads_audience",
    reference_type=MetaAdsAudienceReference,
    search=search_meta_ads_audiences,
    resolve=resolve_meta_ads_audiences,
    max_page_size=25,
    requires_active_context=True,
    provider_key="meta_ads",
)
