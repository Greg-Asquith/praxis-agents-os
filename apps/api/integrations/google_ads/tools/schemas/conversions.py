# apps/api/integrations/google_ads/tools/schemas/conversions.py

"""Arguments and result contract for changing conversion actions and account goals."""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...operations.conversion_settings import ConversionSetting, decimal_text
from ...references import GoogleAdsConversionActionReference, GoogleAdsConversionGoalReference
from .base import GoogleAdsStrictModel

MAX_CONVERSION_UPDATES = 50


class GoogleAdsConversionActionUpdate(GoogleAdsStrictModel):
    """One conversion action and only the settings that change."""

    conversion_action: GoogleAdsConversionActionReference
    status: Literal["ENABLED", "HIDDEN"] | None = None
    # Primary actions count in Conversions and bidding; secondary ones only in All Conversions.
    primary: bool | None = None
    # In `currency`, or the account currency. Zero is allowed, for actions with no value.
    default_value: Annotated[str, Field(pattern=r"^\d{1,12}(\.\d{1,6})?$")] | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    always_use_default_value: bool | None = None
    counting: Literal["ONE_PER_CLICK", "MANY_PER_CLICK"] | None = None
    click_through_days: Annotated[int, Field(ge=1, le=90)] | None = None
    view_through_days: Annotated[int, Field(ge=1, le=30)] | None = None

    @model_validator(mode="after")
    def _something_changes(self) -> Self:
        if not self.requested:
            raise ValueError(
                "Name at least one setting to change for conversion action "
                f"{self.conversion_action.label}."
            )
        return self

    @property
    def resource_name(self) -> str:
        return self.conversion_action.resource_name

    @property
    def requested(self) -> dict[ConversionSetting, Any]:
        """The settings that change, in card terms: the value as a canonical decimal string."""
        values: dict[ConversionSetting, Any] = {}
        for setting in (
            "status",
            "primary",
            "default_value",
            "currency",
            "always_use_default_value",
            "counting",
            "click_through_days",
            "view_through_days",
        ):
            value = getattr(self, setting)
            if value is not None:
                values[setting] = decimal_text(value) if setting == "default_value" else value
        return values


class GoogleAdsAccountGoalUpdate(GoogleAdsStrictModel):
    """Whether one account goal, a conversion category from one origin, counts for bidding."""

    goal: GoogleAdsConversionGoalReference
    biddable: bool

    @property
    def resource_name(self) -> str:
        return self.goal.resource_name

    @property
    def requested(self) -> dict[ConversionSetting, Any]:
        return {"biddable": self.biddable}


class GoogleAdsUpdateConversionsRequest(GoogleAdsStrictModel):
    """Every argument of a conversion update, so an edited approval is checked whole."""

    changes: list[GoogleAdsConversionActionUpdate] = Field(
        default_factory=list, max_length=MAX_CONVERSION_UPDATES
    )
    account_goals: list[GoogleAdsAccountGoalUpdate] = Field(
        default_factory=list, max_length=MAX_CONVERSION_UPDATES
    )

    @model_validator(mode="after")
    def _one_account_each_once(self) -> Self:
        if not self.changes and not self.account_goals:
            raise ValueError("Name at least one conversion action or account goal to change.")
        names = [item.resource_name for item in (*self.changes, *self.account_goals)]
        if len(set(names)) != len(names):
            raise ValueError("List each conversion action and account goal once.")
        if len({self.customer_id_of(item) for item in (*self.changes, *self.account_goals)}) > 1:
            raise ValueError("Change conversions in one Google Ads account per call.")
        return self

    @staticmethod
    def customer_id_of(item: GoogleAdsConversionActionUpdate | GoogleAdsAccountGoalUpdate) -> str:
        if isinstance(item, GoogleAdsConversionActionUpdate):
            return item.conversion_action.customer_id
        return item.goal.customer_id

    @property
    def customer_id(self) -> str:
        return self.customer_id_of((*self.changes, *self.account_goals)[0])


type GoogleAdsConversionSettingValue = str | bool | int | None


class GoogleAdsConversionSettingOutcome(GoogleAdsStrictModel):
    setting: ConversionSetting
    # As the approval card showed it.
    before: GoogleAdsConversionSettingValue
    requested: GoogleAdsConversionSettingValue
    # Read back after the change; meaningful only when the item's `read_back` is true.
    after: GoogleAdsConversionSettingValue
    outcome: Literal["updated", "already_set", "failed", "unverified"]


class GoogleAdsConversionUpdateOutcome(GoogleAdsStrictModel):
    resource_name: str
    kind: Literal["conversion_action", "account_goal"]
    # The action's name, or for an account goal its category and origin tokens.
    name: str
    category: str | None = None
    origin: str | None = None
    read_back: bool
    settings: list[GoogleAdsConversionSettingOutcome] = Field(max_length=8)
    error_code: str | None = None
    message: str | None = None


class GoogleAdsUpdateConversionsData(GoogleAdsStrictModel):
    account_id: str
    currency: str
    items: list[GoogleAdsConversionUpdateOutcome] = Field(max_length=2 * MAX_CONVERSION_UPDATES)


class GoogleAdsUpdateConversionsEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateConversionsData | None = None


class GoogleAdsUpdateConversionsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateConversionsEntry]
