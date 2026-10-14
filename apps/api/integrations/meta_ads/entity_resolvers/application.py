# apps/api/integrations/meta_ads/entity_resolvers/application.py

"""Advertisable app lookup for shared runtime entity selectors."""

from collections.abc import Sequence

from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.entity_references import EntityResolverContext, EntityResolverDefinition
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient
from ..operations.list_assets import read_application_references
from ..references import MetaAdsApplicationReference
from .utils import asset_read_args, resolve_assets, search_assets


async def _read(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    budget: ReportResultBudget,
    _references: Sequence[MetaAdsApplicationReference] = (),
) -> list[MetaAdsApplicationReference]:
    found, _more = await read_application_references(client, **asset_read_args(entry, budget))
    return found


async def search_meta_ads_applications(
    ctx: EntityResolverContext, search, _dependent_args, page_size, cursor
):
    return await search_assets(ctx, search, page_size=page_size, cursor=cursor, read=_read)


async def resolve_meta_ads_applications(ctx: EntityResolverContext, values, _dependent_args):
    return await resolve_assets(ctx, values, reference_type=MetaAdsApplicationReference, read=_read)


META_ADS_APPLICATION_RESOLVER = EntityResolverDefinition(
    entity_kind="meta_ads_application",
    reference_type=MetaAdsApplicationReference,
    search=search_meta_ads_applications,
    resolve=resolve_meta_ads_applications,
    max_page_size=25,
    requires_active_context=True,
    provider_key="meta_ads",
)
