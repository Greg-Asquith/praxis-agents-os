// apps/web/src/integrations/meta_ads/lib/copy-ads.ts

import { AD_FORMATS, type AdFormat } from "@/integrations/meta_ads/lib/automatic-changes"
import {
  parseAdSets,
  STATUSES,
  type AdSetInfo,
  type AdStatus,
  type PreviewMedia,
} from "@/integrations/meta_ads/lib/create-ads-args"
import { previewUrl } from "@/integrations/meta_ads/lib/create-ads-result"
import { pluralize } from "@/lib/format"
import { isNonEmptyString, isOneOf, isRecord, isStringArray, stringValue } from "@/lib/guards"

/** What a copy carries from its source ad, as the server read it for the card. */
type CopySource = {
  name: string
  format: AdFormat | null
  excerpt: string | null
  media: PreviewMedia | null
  automaticChanges: string[]
  // True when an AI-generated change is on, so the copy is made paused.
  aiGenerated: boolean
}

export type CopyDraft = {
  index: number
  adId: string
  adSetId: string
  // The source's name as the agent's reference labels it, until the server's read is known.
  sourceLabel: string
  name: string | null
  status: AdStatus
  source: CopySource | null
}

export type CopyAdsArgs = {
  accountId: string | null
  accountName: string | null
  currency: string | null
  adSets: Map<string, AdSetInfo>
  copies: CopyDraft[]
  // The copies argument as sent, so edits keep every field the card doesn't change.
  rawCopies: Record<string, unknown>[]
}

export function parseCopyAdsArgs(value: unknown): CopyAdsArgs | null {
  if (!isRecord(value) || !Array.isArray(value["copies"]) || value["copies"].length === 0)
    return null
  const sources = isRecord(value["_sources"]) ? value["_sources"] : {}
  const copies: CopyDraft[] = []
  const rawCopies: Record<string, unknown>[] = []
  for (const [index, item] of value["copies"].entries()) {
    const copy = isRecord(item) ? parseCopy(item, index, sources) : null
    if (!copy || !isRecord(item)) return null
    copies.push(copy)
    rawCopies.push(item)
  }
  const account = value["_account"]
  return {
    accountId: isRecord(account) ? stringValue(account["account_id"]) : null,
    accountName: stringValue(value["_account_name"]),
    currency: stringValue(value["_currency"]),
    adSets: parseAdSets(value["_ad_sets"]),
    copies,
    rawCopies,
  }
}

function parseCopy(
  item: Record<string, unknown>,
  index: number,
  sources: Record<string, unknown>
): CopyDraft | null {
  const ad = item["ad"]
  const adSet = item["ad_set"]
  const status = item["status"] ?? "paused"
  if (
    !isRecord(ad) ||
    !isRecord(adSet) ||
    !isNonEmptyString(ad["ad_id"]) ||
    !isNonEmptyString(adSet["adset_id"]) ||
    !isOneOf(STATUSES, status)
  )
    return null
  return {
    index,
    adId: ad["ad_id"],
    adSetId: adSet["adset_id"],
    sourceLabel: stringValue(ad["label"]) ?? `Ad ${ad["ad_id"]}`,
    name: stringValue(item["name"]),
    status,
    source: parseSource(sources[ad["ad_id"]]),
  }
}

function parseSource(value: unknown): CopySource | null {
  if (!isRecord(value) || !isNonEmptyString(value["name"])) return null
  const media = value["media"]
  const format = value["format"]
  return {
    name: value["name"],
    format: isOneOf(AD_FORMATS, format) ? format : null,
    excerpt: stringValue(value["excerpt"]),
    media:
      isRecord(media) && isNonEmptyString(media["key"])
        ? {
            key: media["key"],
            mediaType: media["media_type"] === "video" ? "video" : "image",
            label: value["name"],
            width: null,
            height: null,
            ready: true,
            fileId: null,
            revisionId: null,
          }
        : null,
    automaticChanges: isStringArray(value["automatic_changes"]) ? value["automatic_changes"] : [],
    aiGenerated: value["ai_generated"] === true,
  }
}

export function sourceName(copy: CopyDraft): string {
  return copy.source?.name ?? copy.sourceLabel
}

/** Each copy placed in its ad set with the status it starts with, for the delivery lines. */
export function copyRows(args: CopyAdsArgs) {
  return args.copies.map((copy) => ({
    ad: { adSetIds: [copy.adSetId] },
    status: copy.source?.aiGenerated ? ("paused" as const) : copy.status,
  }))
}

/** Sets one copy's name or status; a blank name goes back to the source's name. */
export function editCopy(
  args: CopyAdsArgs,
  index: number,
  key: "name" | "status",
  value: string
): Record<string, unknown>[] {
  return args.rawCopies.map((raw, position) => {
    if (position !== index) return raw
    const { [key]: _previous, ...rest } = raw
    const trimmed = value.trim()
    return trimmed ? { ...rest, [key]: key === "name" ? value : trimmed } : rest
  })
}

/** Blocks approval when two copies would share a name in one ad set. */
export function copyAdsProblem(args: CopyAdsArgs | null): string | null {
  if (!args) return null
  const seen = new Set<string>()
  for (const copy of args.copies) {
    const key = `${copy.adSetId}:${(copy.name ?? sourceName(copy)).trim().toLowerCase()}`
    if (seen.has(key)) return "Give copies in the same ad set different names before approving."
    seen.add(key)
  }
  return null
}

export function copySummary(args: CopyAdsArgs): string {
  const copies = args.copies.length
  const adSets = new Set(args.copies.map((copy) => copy.adSetId)).size
  return `Copy ${String(copies)} ${pluralize(copies, "ad")} into ${String(adSets)} ${pluralize(adSets, "ad set")}${args.accountName ? ` in ${args.accountName}` : ""}.`
}

type CopyOutcome = "copied" | "failed" | "unverified"
type ReviewState = "in_review" | "approved" | "rejected" | "with_issues" | "unknown"

type CopiedAd = {
  sourceName: string | null
  name: string
  adSetId: string
  adSetName: string | null
  requestedStatus: AdStatus
  pausedForAi: boolean
  outcome: CopyOutcome
  recovered: boolean
  adId: string | null
  review: ReviewState
  reviewReasons: string[]
  unexpectedChanges: string[]
  previewUrl: string | null
  errorCode: string | null
  message: string | null
}

export type CopyAdsResult = { accountId: string; copies: CopiedAd[] }

const OUTCOMES: ReadonlySet<CopyOutcome> = new Set(["copied", "failed", "unverified"])
const REVIEW_STATES: ReadonlySet<ReviewState> = new Set([
  "in_review",
  "approved",
  "rejected",
  "with_issues",
  "unknown",
])

export function parseCopyAdsResult(value: unknown): CopyAdsResult | null {
  if (!isRecord(value) || !isNonEmptyString(value["account_id"]) || !Array.isArray(value["copies"]))
    return null
  const copies: CopiedAd[] = []
  for (const item of value["copies"]) {
    const copy = parseCopiedAd(item)
    if (!copy) return null
    copies.push(copy)
  }
  return { accountId: value["account_id"], copies }
}

function parseCopiedAd(value: unknown): CopiedAd | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["name"]) ||
    !isNonEmptyString(value["adset_id"]) ||
    !isOneOf(STATUSES, value["requested_status"]) ||
    !isOneOf(OUTCOMES, value["outcome"]) ||
    !isOneOf(REVIEW_STATES, value["review"])
  )
    return null
  return {
    sourceName: stringValue(value["source_name"]),
    name: value["name"],
    adSetId: value["adset_id"],
    adSetName: stringValue(value["adset_name"]),
    requestedStatus: value["requested_status"],
    pausedForAi: value["paused_for_ai"] === true,
    outcome: value["outcome"],
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

/** Names what to do next, from what the copies were made as. */
export function copyNextStep(result: CopyAdsResult): string | null {
  const copied = result.copies.filter((copy) => copy.outcome === "copied")
  if (copied.length === 0) return null
  if (copied.some((copy) => copy.unexpectedChanges.length > 0)) {
    return "Meta turned on advanced settings some source ads don't have. Check those copies in Ads Manager."
  }
  return copied.every((copy) => copy.requestedStatus === "paused")
    ? "Turn these copies on when Meta approves them. Ask the agent to check their review."
    : "Active copies start running once Meta approves them."
}
