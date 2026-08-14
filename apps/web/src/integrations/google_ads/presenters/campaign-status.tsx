// apps/web/src/integrations/google_ads/presenters/campaign-status.tsx

import {
  CampaignFailure,
  CampaignOutcome,
  type CampaignError,
  type CampaignStatusResult,
} from "@/integrations/google_ads/components/campaign-outcome"
import { googleAdsCampaignDetails } from "@/integrations/google_ads/lib/tool-details"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { isRecord } from "@/lib/guards"

export const googleAdsCampaignStatusPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-update-campaign-status",
  variants: {
    google_ads_update_campaign_status: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Update",
        label: "Update Google Ads Campaign Status",
        parseArgs: campaignArgs,
        prompt: "This changes live campaign delivery.",
        title: "Review campaign status change",
      },
      deniedDescription: "This campaign change was declined. Nothing was changed.",
      details: (args) => googleAdsCampaignDetails(args),
      emptyLabel: "No Google Ads accounts were updated.",
      failedDescription: "The update did not finish. No campaign change was confirmed.",
      heading: "Update Campaign Status",
      malformedDescription:
        "The system couldn't verify this account's campaign outcomes. Check the Google Ads platform before taking further action.",
      parseResult: campaignResult,
      progressLabel: "Updating Google Ads campaigns…",
      renderFailure: (args, description) => (
        <CampaignFailure args={args} description={description} />
      ),
      renderOutcome: (result) => <CampaignOutcome result={result} />,
      resultAriaLabel: "Google Ads campaign update results",
      resultFailure:
        "The system couldn't verify the campaign changes. Check the Google Ads platform before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads campaign update",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads applied this campaign change. Check the Google Ads platform before taking further action.",
      waitingLabel: "Waiting for campaign approval…",
    }),
  },
})

function campaignArgs(value: unknown): Record<string, unknown> | null {
  return isRecord(value) &&
    Array.isArray(value["campaign_ids"]) &&
    value["campaign_ids"].length > 0 &&
    value["campaign_ids"].every(
      (item) =>
        isRecord(item) && typeof item["campaign_id"] === "string" && item["campaign_id"].length > 0
    ) &&
    (value["status"] === "ENABLED" || value["status"] === "PAUSED")
    ? value
    : null
}

function campaignResult(value: unknown): CampaignStatusResult | null {
  if (!isRecord(value) || !Array.isArray(value["campaigns"])) {
    return null
  }
  const errors: CampaignError[] = []
  const succeededIds: string[] = []
  for (const item of value["campaigns"]) {
    if (
      !isRecord(item) ||
      typeof item["campaign_id"] !== "string" ||
      (item["outcome"] !== "updated" && item["outcome"] !== "failed")
    ) {
      return null
    }
    if (item["outcome"] === "updated") {
      succeededIds.push(item["campaign_id"])
    } else {
      errors.push({
        campaignId: item["campaign_id"],
        errorCode: typeof item["error_code"] === "string" ? item["error_code"] : "",
        message: typeof item["message"] === "string" ? item["message"] : "Update failed.",
      })
    }
  }
  return {
    errors,
    succeededIds,
  }
}
