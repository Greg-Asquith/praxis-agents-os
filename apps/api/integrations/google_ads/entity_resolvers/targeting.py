# apps/api/integrations/google_ads/entity_resolvers/targeting.py

"""Location and language lookup, so an approval card can add targeting Google itself returned."""

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field

from integrations.google_ads.operations.search_targeting import (
    MAX_LOCATION_NAMES,
    LanguageOption,
    LocationOption,
    matching_languages,
    read_languages,
    read_locations,
    search_locations,
)
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverContext,
    EntityResolverDefinition,
    EntityResolverPage,
    ScopedEntityReference,
)

type _Key = Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]


class _TargetOption(ScopedEntityReference):
    customer_id: Annotated[str, Field(pattern=r"^\d{1,32}$")]
    key: _Key
    name: str | None = Field(default=None, max_length=500)

    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "key",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return self.key


class GoogleAdsLocationOption(_TargetOption):
    """A location for the card: copy key, name, and target_type into a location change."""

    entity_kind: Literal["google_ads_location"] = "google_ads_location"
    target_type: str | None = Field(default=None, max_length=64)
    # The pasted line this location matched, so the card can count lines Google didn't find.
    search_term: str | None = Field(default=None, max_length=500)


class GoogleAdsLanguageOption(_TargetOption):
    """A language for the card: copy key and name into a language change."""

    entity_kind: Literal["google_ads_language"] = "google_ads_language"


def _location_choice(customer_id: str, option: LocationOption) -> EntityChoice:
    place = [
        option.target_type.replace("_", " ").title() if option.target_type else None,
        option.region,
    ]
    reference = GoogleAdsLocationOption(
        customer_id=customer_id,
        key=option.key,
        name=option.name[:500],
        label=option.name[:500],
        description=" · ".join(part for part in place if part)[:1000] or None,
        target_type=option.target_type,
        search_term=option.search_term,
    )
    return EntityChoice.from_reference(reference, icon="google_ads")


def _language_choice(customer_id: str, option: LanguageOption) -> EntityChoice:
    reference = GoogleAdsLanguageOption(
        customer_id=customer_id, key=option.key, name=option.name[:500], label=option.name[:500]
    )
    return EntityChoice.from_reference(reference, icon="google_ads")


async def _first_client(ctx: EntityResolverContext) -> tuple[Any, Any] | None:
    """Google's constants are the same for every account, so the first selected one reads them."""
    entries = ctx.active_context.compatible_entries(GOOGLE_ADS_BINDING)
    if not entries:
        return None
    client = await google_ads_client_for_principal(
        ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entries[0]
    )
    return client, entries[0]


async def search_location_options(
    ctx: EntityResolverContext, search: str, _dependent_args, page_size: int, _cursor
) -> EntityResolverPage:
    """Searches one name, or a pasted list with one name per line and only each best match."""
    names = list(dict.fromkeys(line.strip() for line in search.splitlines() if line.strip()))
    found = await _first_client(ctx) if names else None
    if found is None:
        return EntityResolverPage(choices=())
    client, entry = found
    options = await search_locations(client, names=names[:MAX_LOCATION_NAMES])
    if len(names) > 1:
        best: dict[str | None, LocationOption] = {}
        for option in options:
            best.setdefault(option.search_term, option)
        options = list(best.values())
    return EntityResolverPage(
        choices=tuple(_location_choice(entry.external_id, option) for option in options[:page_size])
    )


async def resolve_location_options(
    ctx: EntityResolverContext, values: Sequence[Any], _dependent_args: Mapping[str, Any]
) -> tuple[EntityChoice, ...]:
    keys = [
        reference.key
        for value in values
        if (reference := _validated(GoogleAdsLocationOption, value)) is not None
    ]
    found = await _first_client(ctx) if keys else None
    if found is None:
        return ()
    client, entry = found
    options = await read_locations(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        keys=keys,
    )
    return tuple(_location_choice(entry.external_id, option) for option in options.values())


async def search_language_options(
    ctx: EntityResolverContext, search: str, _dependent_args, page_size: int, _cursor
) -> EntityResolverPage:
    found = await _first_client(ctx)
    if found is None:
        return EntityResolverPage(choices=())
    client, entry = found
    languages = await read_languages(
        client, customer_id=entry.external_id, login_customer_id=login_customer_id(entry)
    )
    return EntityResolverPage(
        choices=tuple(
            _language_choice(entry.external_id, option)
            for option in matching_languages(languages, search)[:page_size]
        )
    )


async def resolve_language_options(
    ctx: EntityResolverContext, values: Sequence[Any], _dependent_args: Mapping[str, Any]
) -> tuple[EntityChoice, ...]:
    keys = {
        reference.key
        for value in values
        if (reference := _validated(GoogleAdsLanguageOption, value)) is not None
    }
    found = await _first_client(ctx) if keys else None
    if found is None:
        return ()
    client, entry = found
    languages = await read_languages(
        client, customer_id=entry.external_id, login_customer_id=login_customer_id(entry)
    )
    return tuple(
        _language_choice(entry.external_id, option) for option in languages if option.key in keys
    )


def _validated[T: _TargetOption](model: type[T], value: Any) -> T | None:
    try:
        return model.model_validate(value)
    except ValueError:
        return None


GOOGLE_ADS_LOCATION_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_location",
    reference_type=GoogleAdsLocationOption,
    search=search_location_options,
    resolve=resolve_location_options,
    max_page_size=50,
    requires_active_context=True,
    provider_key="google_ads",
)
GOOGLE_ADS_LANGUAGE_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_language",
    reference_type=GoogleAdsLanguageOption,
    search=search_language_options,
    resolve=resolve_language_options,
    max_page_size=50,
    requires_active_context=True,
    provider_key="google_ads",
)
