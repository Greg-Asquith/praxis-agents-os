// apps/web/src/integrations/google_ads/presenters/campaign-status.tsx

import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { parseOutcomeList } from "@/integrations/google_ads/lib/envelopes"
import { countByKind } from "@/integrations/google_ads/lib/outcomes"
import {
  campaignReferenceLabels,
  googleAdsCampaignDetails,
} from "@/integrations/google_ads/lib/tool-details"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { isRecord } from "@/lib/guards"

export const googleAdsCampaignStatusPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_campaign_status: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Update", object: "campaign status", effect: "updated" },
      approval: {
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
      },
      details: (args) => googleAdsCampaignDetails(args),
      parseResult: campaignResult,
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
