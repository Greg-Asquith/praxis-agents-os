# apps/api/integrations/meta_ads/entity_resolvers/instagram_account.py

"""Instagram account lookup for shared runtime entity selectors."""

from collections.abc import Sequence

from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.entity_references import EntityResolverContext, EntityResolverDefinition
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient
from ..operations.list_assets import read_instagram_references
from ..references import MetaAdsInstagramAccountReference
from .utils import asset_read_args, resolve_assets, search_assets


async def _read(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    budget: ReportResultBudget,
    _references: Sequence[MetaAdsInstagramAccountReference] = (),
) -> list[MetaAdsInstagramAccountReference]:
    accounts, _more = await read_instagram_references(client, **asset_read_args(entry, budget))
    return accounts


async def search_meta_ads_instagram_accounts(
    ctx: EntityResolverContext, search, _dependent_args, page_size, cursor
):
    return await search_assets(ctx, search, page_size=page_size, cursor=cursor, read=_read)


async def resolve_meta_ads_instagram_accounts(ctx: EntityResolverContext, values, _dependent_args):
    return await resolve_assets(
        ctx, values, reference_type=MetaAdsInstagramAccountReference, read=_read
    )


META_ADS_INSTAGRAM_ACCOUNT_RESOLVER = EntityResolverDefinition(
    entity_kind="meta_ads_instagram_account",
    reference_type=MetaAdsInstagramAccountReference,
    search=search_meta_ads_instagram_accounts,
    resolve=resolve_meta_ads_instagram_accounts,
    max_page_size=25,
    requires_active_context=True,
    provider_key="meta_ads",
)
