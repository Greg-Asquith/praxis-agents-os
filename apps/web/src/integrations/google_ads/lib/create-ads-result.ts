// apps/web/src/integrations/google_ads/lib/create-ads-result.ts

import { isNonEmptyString, isRecord } from "@/lib/guards"

export type CreatedAdOutcome = "created" | "failed" | "unverified"

export type CreatedAd = {
  ad: number
  adGroup: string
  adGroupName: string
  approvalStatus: string | null
  campaignName: string | null
  errorCode: string | null
  headline: string
  message: string | null
  outcome: CreatedAdOutcome
  resourceName: string | null
  reviewStatus: string | null
  status: string | null
}

export type CreateAdsResult = {
  accountId: string
  ads: CreatedAd[]
  requestedStatus: "PAUSED" | "ENABLED"
}

const OUTCOMES = new Set<string>(["created", "failed", "unverified"])

function nullableText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null
}

function parseAd(value: unknown): CreatedAd | null {
  if (!isRecord(value)) return null
  const { ad, outcome } = value
  if (
    typeof ad !== "number" ||
    typeof outcome !== "string" ||
    !OUTCOMES.has(outcome) ||
    !isNonEmptyString(value["ad_group"])
  )
    return null
  return {
    ad,
    adGroup: value["ad_group"],
    adGroupName: nullableText(value["ad_group_name"]) ?? value["ad_group"],
    approvalStatus: nullableText(value["approval_status"]),
    campaignName: nullableText(value["campaign_name"]),
    errorCode: nullableText(value["error_code"]),
    headline: nullableText(value["headline"]) ?? "",
    message: nullableText(value["message"]),
    outcome: outcome as CreatedAdOutcome,
    resourceName: nullableText(value["resource_name"]),
    reviewStatus: nullableText(value["review_status"]),
    status: nullableText(value["status"]),
  }
}

export function parseCreateAdsResult(value: unknown): CreateAdsResult | null {
  if (!isRecord(value) || !isNonEmptyString(value["account_id"]) || !Array.isArray(value["ads"]))
    return null
  const requestedStatus = value["requested_status"]
  if (requestedStatus !== "PAUSED" && requestedStatus !== "ENABLED") return null
  const ads: CreatedAd[] = []
  for (const item of value["ads"]) {
    const ad = parseAd(item)
    if (ad === null) return null
    ads.push(ad)
  }
  return { accountId: value["account_id"], ads, requestedStatus }
}

const REVIEW_LABELS: Record<string, string> = {
  REVIEWED: "Reviewed",
  REVIEW_IN_PROGRESS: "Under Review",
  ELIGIBLE_MAY_SERVE: "Eligible",
  UNDER_APPEAL: "Under Appeal",
}

const APPROVAL_LABELS: Record<string, string> = {
  APPROVED: "Approved",
  APPROVED_LIMITED: "Approved (Limited)",
  AREA_OF_INTEREST_ONLY: "Approved (Limited)",
  DISAPPROVED: "Disapproved",
}

/** Google's review state in words: the decision once there is one, else where the review is. */
export function reviewLabel(ad: CreatedAd): string {
  if (ad.outcome !== "created") return "—"
  const approval = ad.approvalStatus ? APPROVAL_LABELS[ad.approvalStatus] : undefined
  if (approval && ad.reviewStatus === "REVIEWED") return approval
  return (ad.reviewStatus ? REVIEW_LABELS[ad.reviewStatus] : undefined) ?? "Unknown"
}

export function createAdsSummary(result: CreateAdsResult): string {
  const count = (outcome: CreatedAdOutcome) =>
    result.ads.filter((ad) => ad.outcome === outcome).length
  const created = count("created")
  if (created === 0 && count("unverified") === 0) return "nothing created"
  const state = result.requestedStatus === "ENABLED" ? "on" : "paused"
  return [
    created ? `${String(created)} created, ${state}` : null,
    count("failed") ? `${String(count("failed"))} failed` : null,
    count("unverified") ? `${String(count("unverified"))} unconfirmed` : null,
  ]
    .filter(Boolean)
    .join(" · ")
}
