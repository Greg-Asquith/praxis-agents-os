// apps/web/src/integrations/google_ads/presenters/campaign-links.tsx

import { googleAdsWriteCopy } from "@/integrations/google_ads/lib/copy"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"

import {
  CampaignLinkApprovalSummary,
  CampaignLinkOutcome,
  type CampaignLinkCampaignOutcome,
  type CampaignLinkResult,
} from "@/integrations/google_ads/components/campaign-link-outcome"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { isOneOf, isRecord } from "@/lib/guards"

const copySpec = { object: "campaign shared list" }
const copy = googleAdsWriteCopy({
  verb: "Update",
  ...copySpec,
  effect: "updated",
})
const linkCopy = googleAdsWriteCopy({ ...copySpec, verb: "Link", effect: "linked" })
const unlinkCopy = googleAdsWriteCopy({ ...copySpec, verb: "Unlink", effect: "unlinked" })

export const googleAdsCampaignLinksPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-negative-list-campaign-links",
  variants: {
    google_ads_link_negative_keyword_list: defineGoogleAdsWriteVariant({
      ...copy,
      approval: {
        ...copy.approval,
        title: (args) =>
          args.action === "UNLINK" ? unlinkCopy.approval.title : linkCopy.approval.title,
        parseArgs: campaignLinkArgs,
        prompt: (args) =>
          args.action === "LINK"
            ? "Review which live campaigns will start using this negative keyword list."
            : "Review which live campaigns will stop using this negative keyword list.",
        renderSummary: (value, fallback) => {
          const currentArgs = campaignLinkArgs(value) ?? fallback
          return (
            <CampaignLinkApprovalSummary
              campaignCount={currentArgs.campaignIds.length}
              listName={currentArgs.negativeList.name}
            />
          )
        },
      },
      details: campaignLinkDetails,
      progressLabel: (args) =>
        args?.action === "UNLINK" ? unlinkCopy.progressLabel : linkCopy.progressLabel,
      parseResult: campaignLinkResult,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets targets={args?.campaignLabels ?? []} description={description} />
      ),
      renderOutcome: (result) => <CampaignLinkOutcome result={result} />,
    }),
  },
})

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
    if (!isRecord(campaign) || typeof campaign["campaign_id"] !== "string") {
      return null
    }
    const campaignId = campaign["campaign_id"].trim()
    if (!campaignId) {
      return null
    }
    campaignIds.push(campaignId)
    const label = typeof campaign["label"] === "string" ? campaign["label"].trim() : ""
    campaignLabels.push(label || campaignId)
  }
  const list = value["negative_list"]
  const listName = typeof list["label"] === "string" ? list["label"].trim() : ""
  const listId = typeof list["shared_set_id"] === "string" ? list["shared_set_id"].trim() : ""
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
    { label: "Action", value: googleAdsTokenLabel(args.action, args.action) },
  ]
}

function campaignLinkResult(value: unknown): CampaignLinkResult | null {
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
    !isRecord(list["reference"]) ||
    typeof list["reference"]["shared_set_id"] !== "string" ||
    typeof list["name"] !== "string" ||
    (list["member_count"] !== null &&
      (typeof list["member_count"] !== "number" ||
        !Number.isInteger(list["member_count"]) ||
        list["member_count"] < 0))
  ) {
    return null
  }
  const action = value["action"]
  const allowedOutcomes: ReadonlySet<CampaignLinkCampaignOutcome["outcome"]> =
    action === "LINK"
      ? new Set(["linked", "already_linked", "failed"])
      : new Set(["unlinked", "not_linked", "failed"])
  const campaigns: CampaignLinkCampaignOutcome[] = []
  for (const campaign of value["campaigns"]) {
    const outcome = isRecord(campaign) ? campaign["outcome"] : undefined
    if (
      !isRecord(campaign) ||
      typeof campaign["campaign_id"] !== "string" ||
      typeof campaign["campaign_name"] !== "string" ||
      !isOneOf(allowedOutcomes, outcome) ||
      (campaign["external_ref"] !== null && typeof campaign["external_ref"] !== "string")
    ) {
      return null
    }
    const failed = outcome === "failed"
    const applied = outcome === "linked" || outcome === "unlinked"
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
      errorCode:
        failed && typeof campaign["error_code"] === "string" ? campaign["error_code"] : null,
      externalRef: campaign["external_ref"],
      message: failed && typeof campaign["message"] === "string" ? campaign["message"] : null,
      outcome,
    })
  }
  return {
    action,
    campaigns,
    negativeList: {
      externalId: list["reference"]["shared_set_id"],
      memberCount: list["member_count"],
      name: list["name"] || list["reference"]["shared_set_id"],
    },
  }
}
