# apps/api/integrations/meta_ads/entity_resolvers/targeting.py

"""Place and interest lookup, so an approval card can add targeting Meta itself returned."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field

from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverContext,
    EntityResolverDefinition,
    EntityResolverPage,
)

from ..models import MetaAdsText
from ..operations.search_targeting import search_targeting
from ..operations.targeting import MetaAdsCountryCode, MetaAdsLocationKind, MetaAdsTargetingKey
from ..references import MetaAdsAccountReference
from ..tools.schemas.targeting import MetaAdsTargetingKind, MetaAdsTargetingOption
from ..tools.utils.bindings import META_ADS_BINDING
from ..tools.utils.client import meta_ads_client_for_principal

_PLACE_KINDS: tuple[MetaAdsLocationKind, ...] = ("country", "region", "city", "postcode")


class MetaAdsLocationOption(MetaAdsAccountReference):
    """A place for MetaAdsTargeting: copy kind, key, name, and country_code into a location."""

    entity_kind: Literal["meta_ads_targeting_location"] = "meta_ads_targeting_location"
    kind: MetaAdsLocationKind
    key: MetaAdsTargetingKey
    name: MetaAdsText | None = None
    country_code: MetaAdsCountryCode | None = None

    identity_fields: ClassVar[tuple[str, ...]] = (
        *MetaAdsAccountReference.identity_fields,
        "kind",
        "key",
    )

    @property
    def provider_entity_id(self) -> str:
        return f"{self.kind}:{self.key}"


class MetaAdsInterestOption(MetaAdsAccountReference):
    """An interest for MetaAdsTargeting: copy kind, key, and name into a detailed item."""

    entity_kind: Literal["meta_ads_targeting_interest"] = "meta_ads_targeting_interest"
    kind: Literal["interest"] = "interest"
    key: Annotated[str, Field(pattern=r"^[0-9]{1,32}$")]
    name: MetaAdsText | None = None

    identity_fields: ClassVar[tuple[str, ...]] = (
        *MetaAdsAccountReference.identity_fields,
        "kind",
        "key",
    )

    @property
    def provider_entity_id(self) -> str:
        return self.key


async def _find(
    ctx: EntityResolverContext, kinds: Sequence[MetaAdsTargetingKind], query: str, limit: int
) -> list[tuple[str, MetaAdsTargetingOption]]:
    """Searches Meta once per kind; Meta's keys don't depend on the ad account, so one runs it."""
    entries = ctx.active_context.compatible_entries(META_ADS_BINDING)
    if not entries or not query.strip():
        return []
    client = await meta_ads_client_for_principal(
        ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entries[0]
    )
    found = await asyncio.gather(
        *(
            search_targeting(
                client,
                account_id=entries[0].external_id,
                kind=kind,
                query=query,
                country_code=None,
                limit=limit,
            )
            for kind in kinds
        )
    )
    return [(entries[0].external_id, option) for data in found for option in data.options]


def _location(account_id: str, option: MetaAdsTargetingOption) -> EntityChoice:
    reference = MetaAdsLocationOption(
        account_id=account_id,
        label=option.name[:500],
        description=", ".join(part for part in (option.region, option.description) if part) or None,
        kind=option.kind,
        key=option.key,
        name=option.name,
        country_code=option.country_code,
    )
    return EntityChoice.from_reference(reference, icon="meta_ads")


def _interest(account_id: str, option: MetaAdsTargetingOption) -> EntityChoice:
    reference = MetaAdsInterestOption(
        account_id=account_id,
        label=option.name[:500],
        description=option.description,
        key=option.key,
        name=option.name,
    )
    return EntityChoice.from_reference(reference, icon="meta_ads")


async def search_locations(
    ctx: EntityResolverContext, search: str, _dependent_args, page_size: int, _cursor
) -> EntityResolverPage:
    options = await _find(ctx, _PLACE_KINDS, search, page_size)
    return EntityResolverPage(
        choices=tuple(_location(account, option) for account, option in options[:page_size])
    )


async def search_interests(
    ctx: EntityResolverContext, search: str, _dependent_args, page_size: int, _cursor
) -> EntityResolverPage:
    options = await _find(ctx, ("interest",), search, page_size)
    return EntityResolverPage(
        choices=tuple(_interest(account, option) for account, option in options[:page_size])
    )


async def _confirm(
    ctx: EntityResolverContext,
    values: Sequence[Any],
    *,
    reference_type: type[MetaAdsLocationOption] | type[MetaAdsInterestOption],
) -> dict[tuple[str, str], tuple[str, MetaAdsTargetingOption]]:
    """Finds each named item in Meta's own search, keyed by kind and key."""
    confirmed: dict[tuple[str, str], tuple[str, MetaAdsTargetingOption]] = {}
    for value in values:
        try:
            reference = reference_type.model_validate(value)
        except ValueError:
            continue
        if reference.name is None:
            continue
        for account, option in await _find(ctx, [reference.kind], reference.name, 25):
            if (account, option.kind, option.key) == (
                reference.account_id,
                reference.kind,
                reference.key,
            ):
                confirmed[(option.kind, option.key)] = (account, option)
    return confirmed


async def resolve_locations(
    ctx: EntityResolverContext, values: Sequence[Any], _dependent_args: Mapping[str, Any]
) -> tuple[EntityChoice, ...]:
    found = await _confirm(ctx, values, reference_type=MetaAdsLocationOption)
    return tuple(_location(account, option) for account, option in found.values())


async def resolve_interests(
    ctx: EntityResolverContext, values: Sequence[Any], _dependent_args: Mapping[str, Any]
) -> tuple[EntityChoice, ...]:
    found = await _confirm(ctx, values, reference_type=MetaAdsInterestOption)
    return tuple(_interest(account, option) for account, option in found.values())


META_ADS_LOCATION_RESOLVER = EntityResolverDefinition(
    entity_kind="meta_ads_targeting_location",
    reference_type=MetaAdsLocationOption,
    search=search_locations,
    resolve=resolve_locations,
    max_page_size=25,
    requires_active_context=True,
    provider_key="meta_ads",
)
META_ADS_INTEREST_RESOLVER = EntityResolverDefinition(
    entity_kind="meta_ads_targeting_interest",
    reference_type=MetaAdsInterestOption,
    search=search_interests,
    resolve=resolve_interests,
    max_page_size=25,
    requires_active_context=True,
    provider_key="meta_ads",
)
