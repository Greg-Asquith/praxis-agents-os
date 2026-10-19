# apps/api/integrations/meta_ads/tools/schemas/targeting_edits.py

"""Input and result contracts for changing who existing ad sets reach."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText
from ...operations.targeting import (
    MetaAdsDetailedItem,
    MetaAdsLocation,
    MetaAdsLocationKind,
    MetaAdsTargetingKey,
)
from ...operations.targeting_reader import (
    MetaAdsTargetingRead,
    MetaAdsTargetingSection,
)
from ...references import MetaAdsAdSetReference, MetaAdsAudienceReference
from .ad_sets import MetaAdsEuName

MAX_TARGETING_EDITS = 20
_MAX_ITEMS = 50

type MetaAdsDetailedKey = Annotated[str, Field(pattern=r"^[0-9]{1,32}$")]
type MetaAdsLanguageKey = Annotated[str, Field(pattern=r"^[0-9]{1,16}$")]
type MetaAdsAge = Annotated[int, Field(ge=13, le=65)]
type MetaAdsDetailedGroups = Annotated[
    list[Annotated[list[MetaAdsDetailedItem], Field(min_length=1, max_length=25)]],
    Field(max_length=5),
]


class MetaAdsLocationKey(MetaAdsStrictModel):
    """A place the ad set already targets or excludes, as meta_ads_list_objects or search named it."""

    kind: MetaAdsLocationKind
    key: MetaAdsTargetingKey
    name: MetaAdsText | None = Field(default=None, description="Display only.")


class MetaAdsDetailedAddition(MetaAdsStrictModel):
    group: int = Field(
        ge=1,
        le=5,
        description="1 for the first group; one more than the last group starts a new group.",
    )
    items: list[MetaAdsDetailedItem] = Field(min_length=1, max_length=25)


class MetaAdsTargetingEdit(MetaAdsStrictModel):
    """Additions, removals, and new values for one ad set; anything omitted stays as it is."""

    ad_set: MetaAdsAdSetReference
    add_locations: list[MetaAdsLocation] = Field(default_factory=list, max_length=_MAX_ITEMS)
    remove_locations: list[MetaAdsLocationKey] = Field(default_factory=list, max_length=_MAX_ITEMS)
    add_excluded_locations: list[MetaAdsLocation] = Field(
        default_factory=list, max_length=_MAX_ITEMS
    )
    remove_excluded_locations: list[MetaAdsLocationKey] = Field(
        default_factory=list, max_length=_MAX_ITEMS
    )
    location_types: Literal["home_or_recent", "home"] | None = None
    age_min: MetaAdsAge | None = None
    age_max: MetaAdsAge | Literal["none"] | None = Field(
        default=None, description="13 to 65, or none to reach 65 and over."
    )
    genders: Literal["all", "men", "women"] | None = None
    languages: list[MetaAdsLanguageKey] | Literal["all"] | None = Field(
        default=None, description="Replaces the language list; all removes it."
    )
    detailed: MetaAdsDetailedGroups | Literal["none"] | None = Field(
        default=None, description="Replaces every detailed targeting group; none removes them."
    )
    add_detailed_items: MetaAdsDetailedAddition | None = None
    remove_detailed_items: list[MetaAdsDetailedKey] = Field(
        default_factory=list, max_length=_MAX_ITEMS
    )
    add_audiences: list[MetaAdsAudienceReference] = Field(default_factory=list, max_length=25)
    remove_audiences: list[MetaAdsAudienceReference] = Field(default_factory=list, max_length=25)
    add_excluded_audiences: list[MetaAdsAudienceReference] = Field(
        default_factory=list, max_length=25
    )
    remove_excluded_audiences: list[MetaAdsAudienceReference] = Field(
        default_factory=list, max_length=25
    )
    advantage_audience: bool | None = None
    eu_payer: MetaAdsEuName | None = None
    eu_beneficiary: MetaAdsEuName | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not self.sections:
            raise ValueError("Set at least one targeting change for each ad set.")
        if self.detailed is not None and (self.add_detailed_items or self.remove_detailed_items):
            raise ValueError("Replace detailed groups or add and remove items, not both.")
        audiences = (
            *self.add_audiences,
            *self.remove_audiences,
            *self.add_excluded_audiences,
            *self.remove_excluded_audiences,
        )
        if any(item.account_id != self.ad_set.account_id for item in audiences):
            raise ValueError("Use audiences from the ad set's ad account.")
        return self

    @property
    def sections(self) -> tuple[MetaAdsTargetingSection, ...]:
        """The targeting sections this edit changes."""
        changed = {
            "locations": bool(self.add_locations or self.remove_locations)
            or self.location_types is not None,
            "excluded_locations": bool(
                self.add_excluded_locations or self.remove_excluded_locations
            ),
            "ages": self.age_min is not None or self.age_max is not None,
            "genders": self.genders is not None,
            "languages": self.languages is not None,
            "detailed": self.detailed is not None
            or bool(self.add_detailed_items or self.remove_detailed_items),
            "audiences": bool(self.add_audiences or self.remove_audiences),
            "excluded_audiences": bool(
                self.add_excluded_audiences or self.remove_excluded_audiences
            ),
            "advantage_audience": self.advantage_audience is not None,
        }
        return tuple(section for section, value in changed.items() if value)


class MetaAdsUpdateTargetingRequest(MetaAdsStrictModel):
    """Every argument of a targeting edit, so an edited approval is checked whole."""

    changes: list[MetaAdsTargetingEdit] = Field(min_length=1, max_length=MAX_TARGETING_EDITS)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        ids = [(item.ad_set.account_id, item.ad_set.adset_id) for item in self.changes]
        if len(set(ids)) != len(ids):
            raise ValueError("List each ad set once, with all its targeting changes together.")
        return self


# A section described by keys, such as country:GB,country:IE; home_or_recent.
type MetaAdsSectionValue = Annotated[str, Field(max_length=8000)]


class MetaAdsTargetingSectionChange(MetaAdsStrictModel):
    section: MetaAdsTargetingSection
    before: MetaAdsSectionValue
    requested: MetaAdsSectionValue
    # Read back after the change; null when it couldn't be read.
    after: MetaAdsSectionValue | None


class MetaAdsTargetingEditOutcome(MetaAdsStrictModel):
    adset_id: MetaAdsId
    name: MetaAdsText | None
    # Who the ad set reached before, and who it reaches with the change.
    before: MetaAdsTargetingRead
    requested: MetaAdsTargetingRead
    changes: list[MetaAdsTargetingSectionChange] = Field(max_length=9)
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsUpdateTargetingData(MetaAdsStrictModel):
    account_id: MetaAdsId
    ad_sets: list[MetaAdsTargetingEditOutcome] = Field(max_length=MAX_TARGETING_EDITS)


class MetaAdsUpdateTargetingEntry(IntegrationFanOutEntry):
    data: MetaAdsUpdateTargetingData | None = None


class MetaAdsUpdateTargetingOutput(IntegrationFanOutOutput):
    results: list[MetaAdsUpdateTargetingEntry]
