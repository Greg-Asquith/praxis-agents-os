// apps/web/src/integrations/google_ads/presenters/campaign-links.tsx

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import {
  CampaignLinkApprovalSummary,
  CampaignLinkOutcome,
  type CampaignLinkCampaignOutcome,
  type CampaignLinkResult,
} from "@/integrations/google_ads/components/campaign-link-outcome"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import { formatGoogleAdsAccountId, titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export const googleAdsCampaignLinksPresenter: ToolRowPresenter = {
  handlesApprovals: true,
  key: "google-ads-negative-list-campaign-links",
  matches: (activity) => activity.name === "google_ads_link_negative_keyword_list",
  render: ({ activity, approvalDecision, defaultOpen, ui }) => {
    const originalArgs = campaignLinkArgs(activity.args)
    if (approvalDecision) {
      if (!originalArgs) {
        return null
      }
      const currentArgs =
        campaignLinkArgs(mergeApprovalArgs(activity.args, approvalDecision.decision.edits)) ??
        originalArgs
      const linking = currentArgs.action === "LINK"
      const fields = ui?.arg_fields ?? []
      return (
        <ToolApprovalDecisionCard
          activityId={activity.id}
          approveLabel="Approve & Apply"
          args={activity.args}
          controls={approvalDecision}
          fallbackFields={approvalFallbackFields(activity.args, fields)}
          fields={fields}
          icon={<GoogleAdsLogo className="size-4" />}
          label="Apply Google Ads Negative Keyword List"
          prompt={
            linking
              ? "Review which live campaigns will start using this negative keyword list."
              : "Review which live campaigns will stop using this negative keyword list."
          }
          title={linking ? "Apply negative keyword list" : "Remove negative keyword list"}
          toolName={activity.name}
        >
          <CampaignLinkApprovalSummary
            campaignCount={currentArgs.campaignIds.length}
            listName={currentArgs.negativeList.name}
          />
        </ToolApprovalDecisionCard>
      )
    }
    const action = originalArgs?.action ?? "LINK"
    const linking = action === "LINK"
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={<GoogleAdsToolHeading>Update Campaign List</GoogleAdsToolHeading>}
          label={`${linking ? "Applying" : "Removing"} negative keyword list…`}
        />
      )
    }
    if (activity.status === "awaiting_approval") {
      return (
        <FanOutSkeleton
          heading={<GoogleAdsToolHeading>Update Campaign List</GoogleAdsToolHeading>}
          label="Waiting for campaign approval…"
        />
      )
    }
    if (activity.status === "denied") {
      return campaignLinkFailure(
        activity.id,
        "This campaign list change was declined. Nothing was changed.",
        defaultOpen
      )
    }
    if (activity.status === "failed" || activity.status === "unknown") {
      return campaignLinkFailure(
        activity.id,
        "The update did not finish. No campaign list change was confirmed.",
        defaultOpen
      )
    }
    const fanOut = parseFanOutData(activity.result, (value) =>
      campaignLinkResult(value, originalArgs)
    )
    if (!fanOut) {
      return campaignLinkFailure(
        activity.id,
        "Praxis could not confirm the campaign list changes.",
        defaultOpen
      )
    }
    const { data: results, entries } = fanOut
    return (
      <div aria-label="Google Ads campaign list results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Account"
          defaultOpen={defaultOpen}
          details={campaignLinkDetails(originalArgs)}
          entries={entries}
          emptyLabel="No Google Ads accounts were updated."
          externalLabel="Customer ID"
          formatContextValue={formatGoogleAdsAccountId}
          heading={<GoogleAdsToolHeading>Update Campaign List</GoogleAdsToolHeading>}
        >
          {(_entry, index) => {
            const result = results[index]
            return result ? <CampaignLinkOutcome result={result} /> : null
          }}
        </FanOutShell>
      </div>
    )
  },
}

type CampaignLinkArgs = {
  action: "LINK" | "UNLINK"
  campaignIds: string[]
  campaignLabels: string[]
  negativeList: {
    externalId: string
    memberCount: number | null
    name: string
  }
}

function campaignLinkArgs(value: unknown): CampaignLinkArgs | null {
  if (
    !isRecord(value) ||
    !isRecord(value["negative_list"]) ||
    !Array.isArray(value["campaign_ids"]) ||
    value["campaign_ids"].length === 0 ||
    (value["action"] !== "LINK" && value["action"] !== "UNLINK")
  ) {
    return null
  }
  const campaignIds: string[] = []
  const campaignLabels: string[] = []
  for (const campaign of value["campaign_ids"]) {
    if (!isRecord(campaign) || typeof campaign["external_id"] !== "string") {
      return null
    }
    const campaignId = campaign["external_id"].trim()
    if (!campaignId) {
      return null
    }
    campaignIds.push(campaignId)
    const label = typeof campaign["label"] === "string" ? campaign["label"].trim() : ""
    campaignLabels.push(label || campaignId)
  }
  const list = value["negative_list"]
  const listName = typeof list["label"] === "string" ? list["label"].trim() : ""
  const listId = typeof list["external_id"] === "string" ? list["external_id"].trim() : ""
  const memberCount =
    typeof list["member_count"] === "number" &&
    Number.isInteger(list["member_count"]) &&
    list["member_count"] >= 0
      ? list["member_count"]
      : null
  return {
    action: value["action"],
    campaignIds,
    campaignLabels,
    negativeList: {
      externalId: listId || "Unavailable",
      memberCount,
      name: listName || "Selected negative keyword list",
    },
  }
}

function campaignLinkDetails(args: CampaignLinkArgs | null) {
  if (!args) {
    return []
  }
  return [
    { label: "Negative keyword list", value: args.negativeList.name },
    { label: "Campaigns", value: args.campaignLabels.join(", ") },
    { label: "Action", value: titleCaseToken(args.action, args.action) },
  ]
}

function campaignLinkResult(
  value: unknown,
  args: CampaignLinkArgs | null
): CampaignLinkResult | null {
  const enriched = enrichedCampaignLinkResult(value)
  if (
    enriched ||
    (isRecord(value) && ("action" in value || "campaigns" in value || "negative_list" in value))
  ) {
    return enriched
  }

  const action = args?.action ?? "LINK"
  const skippedKey = action === "LINK" ? "skipped_existing" : "not_found"
  if (
    !isRecord(value) ||
    !Array.isArray(value["resource_names"]) ||
    !value["resource_names"].every((item) => typeof item === "string") ||
    !Array.isArray(value[skippedKey]) ||
    !value[skippedKey].every((item) => typeof item === "string") ||
    !Array.isArray(value["campaign_errors"])
  ) {
    return null
  }
  const campaignNames = new Map(
    (args?.campaignIds ?? []).map((campaignId, index) => [
      campaignId,
      args?.campaignLabels[index] ?? campaignId,
    ])
  )
  const campaigns: CampaignLinkCampaignOutcome[] = value["resource_names"].flatMap(
    (resourceName) => {
      const campaignId = resourceName.slice(resourceName.lastIndexOf("/") + 1).split("~", 1)[0]
      return campaignId
        ? [
            {
              campaignId,
              campaignName: campaignNames.get(campaignId) ?? campaignId,
              errorCode: null,
              externalRef: resourceName,
              message: null,
              outcome: action === "LINK" ? ("linked" as const) : ("unlinked" as const),
            },
          ]
        : []
    }
  )
  for (const campaignId of value[skippedKey]) {
    campaigns.push({
      campaignId,
      campaignName: campaignNames.get(campaignId) ?? campaignId,
      errorCode: null,
      externalRef: null,
      message: null,
      outcome: action === "LINK" ? "already_linked" : "not_linked",
    })
  }
  for (const item of value["campaign_errors"]) {
    if (
      !isRecord(item) ||
      typeof item["campaign_id"] !== "string" ||
      typeof item["message"] !== "string"
    ) {
      return null
    }
    campaigns.push({
      campaignId: item["campaign_id"],
      campaignName: campaignNames.get(item["campaign_id"]) ?? item["campaign_id"],
      errorCode: typeof item["error_code"] === "string" ? item["error_code"] : "unknown",
      externalRef: null,
      message: item["message"],
      outcome: "failed",
    })
  }
  return {
    action,
    campaigns,
    negativeList:
      args?.negativeList ??
      ({
        externalId: "Unavailable",
        memberCount: null,
        name: "Selected negative keyword list",
      } satisfies CampaignLinkResult["negativeList"]),
  }
}

function enrichedCampaignLinkResult(value: unknown): CampaignLinkResult | null {
  if (
    !isRecord(value) ||
    (value["action"] !== "LINK" && value["action"] !== "UNLINK") ||
    !isRecord(value["negative_list"]) ||
    !Array.isArray(value["campaigns"]) ||
    value["campaigns"].length === 0
  ) {
    return null
  }
  const list = value["negative_list"]
  if (
    typeof list["external_id"] !== "string" ||
    typeof list["name"] !== "string" ||
    (list["member_count"] !== null &&
      (typeof list["member_count"] !== "number" ||
        !Number.isInteger(list["member_count"]) ||
        list["member_count"] < 0))
  ) {
    return null
  }
  const action = value["action"]
  const allowedOutcomes =
    action === "LINK"
      ? new Set(["linked", "already_linked", "failed"])
      : new Set(["unlinked", "not_linked", "failed"])
  const campaigns: CampaignLinkCampaignOutcome[] = []
  for (const campaign of value["campaigns"]) {
    if (
      !isRecord(campaign) ||
      typeof campaign["campaign_id"] !== "string" ||
      typeof campaign["campaign_name"] !== "string" ||
      typeof campaign["outcome"] !== "string" ||
      !allowedOutcomes.has(campaign["outcome"]) ||
      (campaign["external_ref"] !== null && typeof campaign["external_ref"] !== "string")
    ) {
      return null
    }
    const failed = campaign["outcome"] === "failed"
    const applied = campaign["outcome"] === "linked" || campaign["outcome"] === "unlinked"
    if (
      (failed &&
        (typeof campaign["message"] !== "string" || typeof campaign["error_code"] !== "string")) ||
      (applied && (typeof campaign["external_ref"] !== "string" || !campaign["external_ref"])) ||
      (!applied && campaign["external_ref"] !== null)
    ) {
      return null
    }
    campaigns.push({
      campaignId: campaign["campaign_id"],
      campaignName: campaign["campaign_name"] || campaign["campaign_id"],
      errorCode: failed ? (campaign["error_code"] as string) : null,
      externalRef: campaign["external_ref"],
      message: failed ? (campaign["message"] as string) : null,
      outcome: campaign["outcome"] as CampaignLinkCampaignOutcome["outcome"],
    })
  }
  return {
    action,
    campaigns,
    negativeList: {
      externalId: list["external_id"],
      memberCount: list["member_count"],
      name: list["name"] || list["external_id"],
    },
  }
}

function campaignLinkFailure(activityId: string, description: string, defaultOpen: boolean) {
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
    <div aria-label="Unconfirmed Google Ads campaign list update" className="w-full min-w-0">
      <FanOutShell
        contextLabel="Account"
        defaultOpen={defaultOpen}
        entries={entries}
        externalLabel="Customer ID"
        formatContextValue={formatGoogleAdsAccountId}
        heading={<GoogleAdsToolHeading>Update Campaign List</GoogleAdsToolHeading>}
        renderFailed={() => <p className="text-destructive text-sm">{description}</p>}
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}
