// apps/web/src/integrations/google_ads/presenters/campaign-status.tsx

import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { parseOutcomeList } from "@/integrations/google_ads/lib/envelopes"
import { countByKind } from "@/integrations/google_ads/lib/outcomes"
import {
  campaignReferenceLabels,
  googleAdsCampaignDetails,
} from "@/integrations/google_ads/lib/tool-details"
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
        renderSummary: (value, fallback) => {
          const labels = campaignReferenceLabels(campaignArgs(value) ?? fallback)
          return (
            <GoogleAdsApprovalSection
              ariaLabel="Proposed campaign status changes"
              countLine={approvalCountLine(labels.length, "campaign")}
            >
              {labels.map((label, index) => (
                <GoogleAdsEntityCard key={`${String(index)}:${label}`} title={label} />
              ))}
            </GoogleAdsApprovalSection>
          )
        },
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
        <GoogleAdsFailureTargets
          targets={campaignReferenceLabels(args)}
          description={description}
        />
      ),
      renderOutcome: (rows) => (
        <GoogleAdsOutcomeTable
          columns={[{ key: "campaign", kind: "text", label: "Campaign" }]}
          rows={rows}
          outcomes={countByKind(rows)}
          exportFilename="google-ads-campaign-status.csv"
        />
      ),
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

function campaignResult(value: unknown) {
  return parseOutcomeList(value, "campaigns", campaignRow, (row) => row.campaignId)
}

function campaignRow(value: unknown): (GoogleAdsOutcomeRow & { campaignId: string }) | null {
  if (
    !isRecord(value) ||
    typeof value["campaign_id"] !== "string" ||
    (value["outcome"] !== "updated" && value["outcome"] !== "failed")
  )
    return null
  return {
    campaignId: value["campaign_id"],
    campaign:
      typeof value["campaign_name"] === "string" && value["campaign_name"]
        ? value["campaign_name"]
        : value["campaign_id"] || "Campaign",
    outcome: value["outcome"],
    details:
      value["outcome"] === "failed"
        ? typeof value["message"] === "string"
          ? value["message"]
          : "Update failed."
        : "",
    errorCode:
      value["outcome"] === "failed" && typeof value["error_code"] === "string"
        ? value["error_code"]
        : "",
  }
}
