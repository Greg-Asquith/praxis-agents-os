# apps/api/integrations/meta_ads/entity_resolvers/campaign.py

"""Meta Ads campaign lookup for shared runtime entity selectors."""

from services.integrations.entity_references import EntityChoice, EntityResolverDefinition

from ..references import MetaAdsCampaignReference
from ..tools.schemas.objects import MetaAdsObject
from .utils import object_label, resolve_objects, search_objects, status_description


def campaign_reference(entry, item: MetaAdsObject, currency: str) -> MetaAdsCampaignReference:
    return MetaAdsCampaignReference(
        account_id=entry.external_id,
        campaign_id=item.id,
        label=object_label(item, "(unnamed campaign)"),
        description=status_description(item, "Campaign"),
        scope_label=entry.display_name,
        status=item.status,
        effective_status=item.effective_status,
        objective=item.objective,
        budget=item.budget,
        currency=currency or None,
    )


def _choice(entry, item: MetaAdsObject, currency: str) -> EntityChoice | None:
    return EntityChoice.from_reference(campaign_reference(entry, item, currency), icon="meta_ads")


async def search_meta_ads_campaigns(ctx, search, _dependent_args, page_size, cursor):
    return await search_objects(
        ctx, search, object_type="campaign", page_size=page_size, cursor=cursor, choice=_choice
    )


async def resolve_meta_ads_campaigns(ctx, values, _dependent_args):
    return await resolve_objects(
        ctx,
        values,
        object_type="campaign",
        reference_type=MetaAdsCampaignReference,
        choice=_choice,
    )


META_ADS_CAMPAIGN_RESOLVER = EntityResolverDefinition(
    entity_kind="meta_ads_campaign",
    reference_type=MetaAdsCampaignReference,
    search=search_meta_ads_campaigns,
    resolve=resolve_meta_ads_campaigns,
    max_page_size=25,
    requires_active_context=True,
    provider_key="meta_ads",
)
