// apps/web/src/integrations/google_ads/presenters/campaign-status.tsx

import { ToolApprovalDecisionCard, type ApprovalField } from "@/components/tool-ui/approval-card"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import {
  CampaignFailure,
  CampaignOutcome,
  type CampaignError,
  type CampaignStatusResult,
} from "@/integrations/google_ads/components/campaign-outcome"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import { googleAdsCampaignDetails } from "@/integrations/google_ads/lib/tool-details"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import { formatGoogleAdsAccountId } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const CAMPAIGN_FIELDS: ApprovalField[] = [
  {
    editable: false,
    format: "list",
    key: "campaign_ids",
    label: "Campaigns",
    options: [],
    placeholder: "",
    secondary: false,
  },
  {
    editable: true,
    format: "text",
    key: "status",
    label: "New status",
    options: ["ENABLED", "PAUSED"],
    placeholder: "",
    secondary: false,
  },
]

export const googleAdsCampaignStatusPresenter: ToolRowPresenter = {
  handlesApprovals: true,
  key: "google-ads-update-campaign-status",
  matches: (activity) => activity.name === "google_ads_update_campaign_status",
  render: ({ activity, approvalDecision, defaultOpen }) => {
    if (approvalDecision) {
      if (!campaignArgs(activity.args)) {
        return null
      }
      return (
        <ToolApprovalDecisionCard
          activityId={activity.id}
          approveLabel="Approve & Update"
          args={activity.args}
          controls={approvalDecision}
          fields={CAMPAIGN_FIELDS}
          icon={<GoogleAdsLogo className="size-4" />}
          label="Update Google Ads Campaign Status"
          prompt="This changes live campaign delivery."
          title="Review campaign status change"
        />
      )
    }
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={<GoogleAdsToolHeading>Update Campaign Status</GoogleAdsToolHeading>}
          label="Updating Google Ads campaigns…"
        />
      )
    }
    if (activity.status === "awaiting_approval") {
      return (
        <FanOutSkeleton
          heading={<GoogleAdsToolHeading>Update Campaign Status</GoogleAdsToolHeading>}
          label="Waiting for campaign approval…"
        />
      )
    }
    if (activity.status === "denied") {
      return campaignFailure(
        activity.id,
        activity.args,
        "This campaign change was declined. Nothing was changed.",
        defaultOpen
      )
    }
    if (activity.status === "failed" || activity.status === "unknown") {
      return campaignFailure(
        activity.id,
        activity.args,
        "The update did not finish. No campaign change was confirmed.",
        defaultOpen
      )
    }
    const fanOut = parseFanOutData(activity.result, campaignResult)
    if (!fanOut) {
      return campaignFailure(
        activity.id,
        activity.args,
        "Praxis could not confirm the campaign changes.",
        defaultOpen
      )
    }
    const { data: results, entries } = fanOut
    return (
      <div aria-label="Google Ads campaign update results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Account"
          defaultOpen={defaultOpen}
          details={googleAdsCampaignDetails(activity.args)}
          entries={entries}
          emptyLabel="No Google Ads accounts were updated."
          externalLabel="Customer ID"
          formatContextValue={formatGoogleAdsAccountId}
          heading={<GoogleAdsToolHeading>Update Campaign Status</GoogleAdsToolHeading>}
        >
          {(_entry, index) => {
            const result = results[index]
            return result ? <CampaignOutcome result={result} /> : null
          }}
        </FanOutShell>
      </div>
    )
  },
}

function campaignFailure(
  activityId: string,
  args: unknown,
  description: string,
  defaultOpen: boolean
) {
  const entries = [
    {
      connectionId: activityId,
      data: null,
      displayName: "Selected Google Ads account",
      errorMessage: description,
      externalId: "Selected Google Ads account",
      status: "failed",
    },
  ]
  return (
    <div aria-label="Unconfirmed Google Ads campaign update" className="w-full min-w-0">
      <FanOutShell
        contextLabel="Account"
        defaultOpen={defaultOpen}
        details={googleAdsCampaignDetails(args)}
        entries={entries}
        externalLabel="Customer ID"
        formatContextValue={formatGoogleAdsAccountId}
        heading={<GoogleAdsToolHeading>Update Campaign Status</GoogleAdsToolHeading>}
        renderFailed={() => <CampaignFailure args={args} description={description} />}
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}

function campaignArgs(value: unknown): boolean {
  return (
    isRecord(value) &&
    Array.isArray(value["campaign_ids"]) &&
    value["campaign_ids"].length > 0 &&
    value["campaign_ids"].every((item) => typeof item === "string") &&
    (value["status"] === "ENABLED" || value["status"] === "PAUSED")
  )
}

function campaignResult(value: unknown): CampaignStatusResult | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["resource_names"]) ||
    !value["resource_names"].every((item) => typeof item === "string") ||
    !Array.isArray(value["campaign_errors"])
  ) {
    return null
  }
  const errors: CampaignError[] = []
  for (const item of value["campaign_errors"]) {
    if (
      !isRecord(item) ||
      typeof item["campaign_id"] !== "string" ||
      typeof item["message"] !== "string"
    ) {
      return null
    }
    errors.push({
      campaignId: item["campaign_id"],
      errorCode:
        typeof item["error_code"] === "string"
          ? item["error_code"]
          : JSON.stringify(item["error_code"] ?? ""),
      message: item["message"],
    })
  }
  return {
    errors,
    succeededIds: value["resource_names"].map((resourceName) =>
      resourceName.slice(resourceName.lastIndexOf("/") + 1)
    ),
  }
}
