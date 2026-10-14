# apps/api/integrations/meta_ads/entity_resolvers/post.py

"""Facebook and Instagram post lookup for shared runtime entity selectors."""

from collections.abc import Sequence

from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.entity_references import EntityResolverContext, EntityResolverDefinition
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient
from ..operations.list_assets import find_post_references, read_post_references
from ..references import MetaAdsPostReference
from .utils import asset_read_args, resolve_assets, search_assets


async def _recent(
    client: MetaAdsClient, entry: ResolvedContextEntry, budget: ReportResultBudget
) -> list[MetaAdsPostReference]:
    posts, _more = await read_post_references(client, **asset_read_args(entry, budget))
    return posts


async def _exact(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    budget: ReportResultBudget,
    references: Sequence[MetaAdsPostReference],
) -> list[MetaAdsPostReference]:
    return await find_post_references(
        client, **asset_read_args(entry, budget), references=references
    )


async def search_meta_ads_posts(
    ctx: EntityResolverContext, search, _dependent_args, page_size, cursor
):
    return await search_assets(ctx, search, page_size=page_size, cursor=cursor, read=_recent)


async def resolve_meta_ads_posts(ctx: EntityResolverContext, values, _dependent_args):
    return await resolve_assets(ctx, values, reference_type=MetaAdsPostReference, read=_exact)


META_ADS_POST_RESOLVER = EntityResolverDefinition(
    entity_kind="meta_ads_post",
    reference_type=MetaAdsPostReference,
    search=search_meta_ads_posts,
    resolve=resolve_meta_ads_posts,
    max_page_size=25,
    requires_active_context=True,
    provider_key="meta_ads",
)
