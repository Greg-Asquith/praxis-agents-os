# apps/api/integrations/google_ads/references/label.py

"""Reusable Google Ads label reference."""

import re
from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.integrations.entity_references import ScopedEntityReference

GOOGLE_ADS_LABEL_NAME_MAX_LENGTH = 80
GOOGLE_ADS_LABEL_DESCRIPTION_MAX_LENGTH = 200
GOOGLE_ADS_LABEL_COLOR_PATTERN = r"^#([a-fA-F0-9]{6}|[a-fA-F0-9]{3})$"


class GoogleAdsLabelAssociationCounts(BaseModel):
    """Live label associations by entity type; `truncated` marks lower bounds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign: int = Field(ge=0)
    ad_group: int = Field(ge=0)
    keyword: int = Field(ge=0)
    # Ad group criteria other than positive keywords, such as negative keywords.
    other_criterion: int = Field(ge=0)
    ad: int = Field(ge=0)
    truncated: bool = False


class GoogleAdsLabelReference(ScopedEntityReference):
    entity_kind: Literal["google_ads_label"] = "google_ads_label"
    customer_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads customer ID, normalized to digits without hyphens.",
    )
    label_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads label ID.",
    )
    status: Literal["ENABLED", "REMOVED"] | None = None
    label_description: str | None = Field(
        default=None,
        max_length=GOOGLE_ADS_LABEL_DESCRIPTION_MAX_LENGTH,
    )
    background_color: str | None = Field(default=None, pattern=GOOGLE_ADS_LABEL_COLOR_PATTERN)
    association_counts: GoogleAdsLabelAssociationCounts | None = None
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "label_id",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return self.label_id


def label_reference_from_row(
    customer_id: str,
    row: Mapping[str, Any],
    *,
    scope_label: str | None,
    association_counts: GoogleAdsLabelAssociationCounts | None = None,
) -> GoogleAdsLabelReference | None:
    """Builds a label reference from one provider `label` row owned by the customer."""
    label_id = str(row.get("id", "")).strip()
    if row.get("resourceName") != f"customers/{customer_id}/labels/{label_id}":
        return None
    text_label = row.get("textLabel")
    text_label = text_label if isinstance(text_label, Mapping) else {}
    name = str(row.get("name", "")).strip()
    description = str(text_label.get("description", "")).strip() or None
    color = str(text_label.get("backgroundColor", "")).strip() or None
    try:
        return GoogleAdsLabelReference(
            customer_id=customer_id,
            label_id=label_id,
            label=name[:500] or "(unnamed label)",
            description=description or "Label",
            scope_label=scope_label,
            status=row.get("status"),
            label_description=description,
            background_color=(
                color if color and re.fullmatch(GOOGLE_ADS_LABEL_COLOR_PATTERN, color) else None
            ),
            association_counts=association_counts,
        )
    except ValidationError:
        return None
