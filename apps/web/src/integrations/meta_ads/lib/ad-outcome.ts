// apps/web/src/integrations/meta_ads/lib/ad-outcome.ts

import { STATUSES, type AdStatus } from "@/integrations/meta_ads/lib/create-ads-args"
import { isNonEmptyString, isOneOf, isStringArray, stringValue } from "@/lib/guards"

type ReviewState = "in_review" | "approved" | "rejected" | "with_issues" | "unknown"

/** What a created or copied ad reports beyond its outcome. */
export type AdOutcomeFields = {
  name: string
  adSetId: string
  adSetName: string | null
  requestedStatus: AdStatus
  recovered: boolean
  adId: string | null
  review: ReviewState
  reviewReasons: string[]
  unexpectedChanges: string[]
  previewUrl: string | null
  errorCode: string | null
  message: string | null
}

export const REVIEW_LABELS = {
  in_review: "In Review",
  approved: "Approved",
  rejected: "Rejected",
  with_issues: "Has Issues",
  unknown: "Not Shown Yet",
} as const

const REVIEW_STATES: ReadonlySet<ReviewState> = new Set([
  "in_review",
  "approved",
  "rejected",
  "with_issues",
  "unknown",
])
const PREVIEW_HOSTS = new Set(["facebook.com", "www.facebook.com", "fb.me"])

export function parseAdOutcomeFields(value: Record<string, unknown>): AdOutcomeFields | null {
  if (
    !isNonEmptyString(value["name"]) ||
    !isNonEmptyString(value["adset_id"]) ||
    !isOneOf(STATUSES, value["requested_status"]) ||
    !isOneOf(REVIEW_STATES, value["review"])
  )
    return null
  return {
    name: value["name"],
    adSetId: value["adset_id"],
    adSetName: stringValue(value["adset_name"]),
    requestedStatus: value["requested_status"],
    recovered: value["recovered"] === true,
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
