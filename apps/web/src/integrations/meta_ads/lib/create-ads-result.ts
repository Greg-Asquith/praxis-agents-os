// apps/web/src/integrations/meta_ads/lib/create-ads-result.ts

import { AD_FORMATS, type AdFormat } from "@/integrations/meta_ads/lib/automatic-changes"
import { STATUSES, type AdStatus } from "@/integrations/meta_ads/lib/create-ads-args"
import {
  parseMediaUploadResult,
  type MediaUploadResult,
} from "@/integrations/meta_ads/lib/media-upload"
import { isNonEmptyString, isOneOf, isRecord, isStringArray, stringValue } from "@/lib/guards"

type CreateOutcome = "created" | "failed" | "unverified"
type ReviewState = "in_review" | "approved" | "rejected" | "with_issues" | "unknown"

type CreatedAd = {
  name: string
  adSetId: string
  adSetName: string | null
  format: AdFormat
  requestedStatus: AdStatus
  outcome: CreateOutcome
  recovered: boolean
  adId: string | null
  review: ReviewState
  reviewReasons: string[]
  unexpectedChanges: string[]
  previewUrl: string | null
  errorCode: string | null
  message: string | null
}

export type CreateAdsResult = {
  accountId: string
  ads: CreatedAd[]
  uploads: MediaUploadResult["uploads"]
  createdOffForAi: boolean
}

const OUTCOMES: ReadonlySet<CreateOutcome> = new Set(["created", "failed", "unverified"])
const REVIEW_STATES: ReadonlySet<ReviewState> = new Set([
  "in_review",
  "approved",
  "rejected",
  "with_issues",
  "unknown",
])
const PREVIEW_HOSTS = new Set(["facebook.com", "www.facebook.com", "fb.me"])

export function parseCreateAdsResult(value: unknown): CreateAdsResult | null {
  if (!isRecord(value) || !isNonEmptyString(value["account_id"]) || !Array.isArray(value["ads"]))
    return null
  const uploads = parseMediaUploadResult({
    account_id: value["account_id"],
    uploads: value["uploads"],
  })
  if (!uploads) return null
  const ads: CreatedAd[] = []
  for (const item of value["ads"]) {
    const ad = parseCreatedAd(item)
    if (!ad) return null
    ads.push(ad)
  }
  return {
    accountId: value["account_id"],
    ads,
    uploads: uploads.uploads,
    createdOffForAi: value["created_off_for_ai"] === true,
  }
}

function parseCreatedAd(value: unknown): CreatedAd | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["name"]) ||
    !isNonEmptyString(value["adset_id"]) ||
    !isOneOf(AD_FORMATS, value["format"]) ||
    !isOneOf(STATUSES, value["requested_status"]) ||
    !isOneOf(OUTCOMES, value["outcome"]) ||
    !isOneOf(REVIEW_STATES, value["review"]) ||
    typeof value["recovered"] !== "boolean"
  )
    return null
  return {
    name: value["name"],
    adSetId: value["adset_id"],
    adSetName: stringValue(value["adset_name"]),
    format: value["format"],
    requestedStatus: value["requested_status"],
    outcome: value["outcome"],
    recovered: value["recovered"],
    adId: stringValue(value["ad_id"]),
    review: value["review"],
    reviewReasons: isStringArray(value["review_reasons"])
      ? value["review_reasons"].slice(0, 5)
      : [],
    unexpectedChanges: isStringArray(value["unexpected_changes"])
      ? value["unexpected_changes"]
      : [],
    previewUrl: previewUrl(value["preview_url"]),
    errorCode: stringValue(value["error_code"]),
    message: stringValue(value["message"]),
  }
}

// Meta's preview link opens only on Facebook's own hosts.
function previewUrl(value: unknown): string | null {
  if (typeof value !== "string") return null
  try {
    const url = new URL(value)
    return url.protocol === "https:" &&
      PREVIEW_HOSTS.has(url.hostname) &&
      !url.username &&
      !url.password
      ? value
      : null
  } catch {
    return null
  }
}

/** Names what to do next, from what the ads were created as. */
export function nextStep(result: CreateAdsResult): string | null {
  const created = result.ads.filter((ad) => ad.outcome === "created")
  if (created.length === 0) return null
  if (created.some((ad) => ad.unexpectedChanges.length > 0)) {
    return "Meta turned on advanced settings you left off for some ads. Check them in Ads Manager, and ask the agent to pause any that are on."
  }
  return created.every((ad) => ad.requestedStatus === "paused")
    ? "Turn these ads on when Meta approves them. Ask the agent to check their review."
    : "Active ads start running once Meta approves them."
}
