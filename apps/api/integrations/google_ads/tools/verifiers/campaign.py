# apps/api/integrations/google_ads/tools/verifiers/campaign.py

"""Live entity-reference verification for Google Ads write tools."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.list_campaign_device_criteria import (
    GoogleAdsCampaignDeviceState,
    list_campaign_device_criteria,
)
from integrations.google_ads.operations.list_campaign_experiment_arms import (
    MAX_ACTIVE_EXPERIMENT_ARMS,
    list_active_campaign_experiment_arms,
)
from integrations.google_ads.operations.list_campaigns import list_campaigns
from integrations.google_ads.tools.utils.routing import login_customer_id
from services.integrations.context.domain import ResolvedContextEntry

from .utils import validated_ids


async def verify_campaigns(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    campaign_ids: Sequence[str],
    ignore_removed: bool,
) -> None:
    """Fail closed unless every approved campaign still exists in its account."""
    normalized_ids = validated_ids(
        campaign_ids,
        invalid_message=(
            "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
        ),
    )
    campaigns = await list_campaigns(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=normalized_ids,
        limit=len(normalized_ids),
        exclude_removed=ignore_removed,
    )
    resolved_ids = {
        str(campaign.get("id", ""))
        for campaign in campaigns
        if not ignore_removed or campaign.get("status") != "REMOVED"
    }
    if resolved_ids != set(normalized_ids):
        raise ModelRetry(
            "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
        )


async def verify_campaigns_for_budget_assignment(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    campaign_ids: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    """Returns complete live campaign budget-assignment state for every target."""
    normalized_ids = validated_ids(
        campaign_ids,
        invalid_message=(
            "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
        ),
    )
    campaigns = await list_campaigns(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=normalized_ids,
        limit=len(normalized_ids),
        exclude_removed=True,
    )
    experiment_arms = await list_active_campaign_experiment_arms(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=normalized_ids,
    )
    if len(experiment_arms) > MAX_ACTIVE_EXPERIMENT_ARMS:
        raise ModelRetry(
            "The selected campaigns have too many active experiment associations to verify. "
            "Choose fewer campaigns and retry."
        )
    campaigns_with_active_trials = _campaign_ids_from_control_arms(
        experiment_arms,
        customer_id=entry.external_id,
    )
    rows_by_id = {
        str(campaign.get("id", "")): {
            **campaign,
            "hasRunningOrScheduledTrials": str(campaign.get("id", ""))
            in campaigns_with_active_trials,
        }
        for campaign in campaigns
    }
    if set(rows_by_id) != set(normalized_ids):
        raise ModelRetry(
            "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
        )
    if any(
        not str(row.get("campaignBudget", "")).startswith(
            f"customers/{entry.external_id}/campaignBudgets/"
        )
        or not str(row.get("experimentType", "")).strip()
        for row in rows_by_id.values()
    ):
        raise ModelRetry(
            "A selected Google Ads campaign has incomplete live budget settings. "
            "Refresh the connection and retry."
        )
    return rows_by_id


def _campaign_ids_from_control_arms(
    rows: Sequence[Mapping[str, Any]],
    *,
    customer_id: str,
) -> set[str]:
    prefix = f"customers/{customer_id}/campaigns/"
    campaign_ids: set[str] = set()
    for row in rows:
        arm = row.get("experimentArm")
        experiment = row.get("experiment")
        if (
            not isinstance(arm, Mapping)
            or arm.get("control") is not True
            or not isinstance(experiment, Mapping)
            or str(experiment.get("status", "")) not in {"INITIATED", "ENABLED"}
        ):
            raise ModelRetry(
                "A selected Google Ads campaign has incomplete live experiment settings. "
                "Refresh the connection and retry."
            )
        resources = arm.get("campaigns")
        if not isinstance(resources, list):
            raise ModelRetry(
                "A selected Google Ads campaign has incomplete live experiment settings. "
                "Refresh the connection and retry."
            )
        for resource in resources:
            value = str(resource)
            campaign_id = value.removeprefix(prefix)
            if value != f"{prefix}{campaign_id}" or not campaign_id.isdigit():
                raise ModelRetry(
                    "A selected Google Ads campaign has incomplete live experiment settings. "
                    "Refresh the connection and retry."
                )
            campaign_ids.add(campaign_id)
    return campaign_ids


async def verify_campaigns_for_device_bidding(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    campaign_ids: Sequence[str],
) -> dict[str, GoogleAdsCampaignDeviceState]:
    """Returns device state after verifying every selected campaign exists."""
    normalized_ids = validated_ids(
        campaign_ids,
        invalid_message=(
            "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
        ),
    )
    states = await list_campaign_device_criteria(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=normalized_ids,
    )
    if set(states) != set(normalized_ids):
        raise ModelRetry(
            "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
        )
    return states
