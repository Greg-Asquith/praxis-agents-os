// apps/web/src/integrations/google_ads/presenters/negative-keywords/campaign.tsx

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import {
  CampaignNegativeKeywordApprovalSummary,
  CampaignNegativeKeywordOutcome,
  type CampaignNegativeKeywordResult,
} from "@/integrations/google_ads/components/negative-keyword-outcome"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import {
  campaignNegativeKeywordArgs,
  campaignNegativeKeywordResult,
  campaignNegativeKeywordSummary,
} from "@/integrations/google_ads/presenters/negative-keywords/utils"
import { formatGoogleAdsAccountId } from "@/lib/format"

export const googleAdsCampaignNegativeKeywordsPresenter: ToolRowPresenter = {
  handlesApprovals: true,
  key: "google-ads-campaign-negative-keywords",
  matches: (activity) =>
    activity.name === "google_ads_add_campaign_negative_keywords" ||
    activity.name === "google_ads_remove_campaign_negative_keywords",
  render: ({ activity, approvalDecision, defaultOpen, ui }) => {
    const removing = activity.name === "google_ads_remove_campaign_negative_keywords"
    const originalArgs = campaignNegativeKeywordArgs(activity.args, removing)
    if (approvalDecision) {
      if (!originalArgs) {
        return null
      }
      const summary = campaignNegativeKeywordSummary(
        mergeApprovalArgs(activity.args, approvalDecision.decision.edits),
        originalArgs
      )
      const fields = ui?.arg_fields ?? []
      return (
        <ToolApprovalDecisionCard
          activityId={activity.id}
          approveLabel={removing ? "Approve & Remove" : "Approve & Add"}
          args={activity.args}
          controls={approvalDecision}
          fallbackFields={approvalFallbackFields(activity.args, fields)}
          fields={fields}
          icon={<GoogleAdsLogo className="size-4" />}
          label={`${removing ? "Remove" : "Add"} Google Ads Campaign Negative Keywords`}
          prompt={
            removing
              ? "Review the campaigns and exclusions. Removing them can re-enable traffic and increase spend."
              : "Review the campaigns and keyword rows before blocking matching traffic."
          }
          title={`${removing ? "Remove" : "Add"} Campaign Negative Keywords`}
          toolName={activity.name}
        >
          <CampaignNegativeKeywordApprovalSummary
            campaignCount={summary.campaignCount}
            keywordCount={summary.keywordCount}
          />
        </ToolApprovalDecisionCard>
      )
    }
    if (activity.status === "running" || activity.status === "awaiting_approval") {
      return (
        <FanOutSkeleton
          heading={<GoogleAdsToolHeading>Campaign Negative Keywords</GoogleAdsToolHeading>}
          label={
            activity.status === "awaiting_approval"
              ? "Waiting for campaign negative keyword approval…"
              : `${removing ? "Removing" : "Adding"} campaign negative keywords…`
          }
        />
      )
    }
    if (
      activity.status === "denied" ||
      activity.status === "failed" ||
      activity.status === "unknown"
    ) {
      const description =
        activity.status === "denied"
          ? `This campaign negative keyword change was declined. Nothing was ${removing ? "removed" : "added"}.`
          : "The update did not finish. No campaign negative keyword change was confirmed."
      return failure(activity.id, description, defaultOpen)
    }
    const fanOut = parseFanOutData<CampaignNegativeKeywordResult>(activity.result, (value) =>
      campaignNegativeKeywordResult(value, removing)
    )
    if (!fanOut) {
      return failure(
        activity.id,
        "Praxis could not confirm the campaign negative keyword changes.",
        defaultOpen
      )
    }
    return (
      <div aria-label="Google Ads campaign negative keyword results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Account"
          defaultOpen={defaultOpen}
          entries={fanOut.entries}
          emptyLabel="No Google Ads accounts changed campaign negative keywords."
          externalLabel="Customer ID"
          formatContextValue={formatGoogleAdsAccountId}
          heading={<GoogleAdsToolHeading>Campaign Negative Keywords</GoogleAdsToolHeading>}
        >
          {(_entry, index) => {
            const result = fanOut.data[index]
            return result ? (
              <CampaignNegativeKeywordOutcome
                action={removing ? "remove" : "add"}
                result={result}
              />
            ) : null
          }}
        </FanOutShell>
      </div>
    )
  },
}

function failure(activityId: string, description: string, defaultOpen: boolean) {
  return (
    <div
      aria-label="Unconfirmed Google Ads campaign negative keyword update"
      className="w-full min-w-0"
    >
      <FanOutShell
        contextLabel="Account"
        defaultOpen={defaultOpen}
        entries={[
          {
            connectionId: activityId,
            data: null,
            displayName: "Selected Google Ads account",
            errorMessage: description,
            externalId: "Selected Google Ads account",
            status: "failed",
          },
        ]}
        externalLabel="Customer ID"
        formatContextValue={formatGoogleAdsAccountId}
        heading={<GoogleAdsToolHeading>Campaign Negative Keywords</GoogleAdsToolHeading>}
        renderFailed={() => <p className="text-destructive text-sm">{description}</p>}
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}
