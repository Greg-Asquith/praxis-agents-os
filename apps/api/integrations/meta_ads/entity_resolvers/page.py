# apps/api/integrations/meta_ads/entity_resolvers/page.py

"""Facebook Page lookup for shared runtime entity selectors."""

from collections.abc import Sequence

from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.entity_references import EntityResolverContext, EntityResolverDefinition
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient
from ..operations.list_assets import read_page_references
from ..references import MetaAdsPageReference
from .utils import asset_read_args, resolve_assets, search_assets


async def _read(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    budget: ReportResultBudget,
    _references: Sequence[MetaAdsPageReference] = (),
) -> list[MetaAdsPageReference]:
    pages, _more = await read_page_references(client, **asset_read_args(entry, budget))
    return pages


async def search_meta_ads_pages(
    ctx: EntityResolverContext, search, _dependent_args, page_size, cursor
):
    return await search_assets(ctx, search, page_size=page_size, cursor=cursor, read=_read)


async def resolve_meta_ads_pages(ctx: EntityResolverContext, values, _dependent_args):
    return await resolve_assets(ctx, values, reference_type=MetaAdsPageReference, read=_read)


META_ADS_PAGE_RESOLVER = EntityResolverDefinition(
    entity_kind="meta_ads_page",
    reference_type=MetaAdsPageReference,
    search=search_meta_ads_pages,
    resolve=resolve_meta_ads_pages,
    max_page_size=25,
    requires_active_context=True,
    provider_key="meta_ads",
)
