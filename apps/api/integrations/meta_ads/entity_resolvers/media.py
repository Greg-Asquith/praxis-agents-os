# apps/api/integrations/meta_ads/entity_resolvers/media.py

"""Ad account image and video lookup for shared runtime entity selectors."""

from collections.abc import Sequence

from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.entity_references import EntityResolverContext, EntityResolverDefinition
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient
from ..operations.list_assets import (
    find_video_references,
    read_image_references,
    read_video_references,
)
from ..references import MetaAdsMediaReference
from .utils import asset_read_args, resolve_assets, search_assets


async def _recent(
    client: MetaAdsClient, entry: ResolvedContextEntry, budget: ReportResultBudget
) -> list[MetaAdsMediaReference]:
    values = asset_read_args(entry, budget)
    images, _more = await read_image_references(client, **values)
    videos, _more = await read_video_references(client, **values)
    return [*images, *videos]


async def _exact(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    budget: ReportResultBudget,
    references: Sequence[MetaAdsMediaReference],
) -> list[MetaAdsMediaReference]:
    values = asset_read_args(entry, budget)
    hashes = sorted({item.image_hash for item in references if item.image_hash})
    video_ids = sorted({item.video_id for item in references if item.video_id})
    images = (await read_image_references(client, **values, hashes=hashes))[0] if hashes else []
    videos = await find_video_references(client, **values, video_ids=video_ids) if video_ids else []
    return [*images, *videos]


async def search_meta_ads_media(
    ctx: EntityResolverContext, search, _dependent_args, page_size, cursor
):
    return await search_assets(ctx, search, page_size=page_size, cursor=cursor, read=_recent)


async def resolve_meta_ads_media(ctx: EntityResolverContext, values, _dependent_args):
    return await resolve_assets(ctx, values, reference_type=MetaAdsMediaReference, read=_exact)


META_ADS_MEDIA_RESOLVER = EntityResolverDefinition(
    entity_kind="meta_ads_media",
    reference_type=MetaAdsMediaReference,
    search=search_meta_ads_media,
    resolve=resolve_meta_ads_media,
    max_page_size=25,
    requires_active_context=True,
    provider_key="meta_ads",
)
