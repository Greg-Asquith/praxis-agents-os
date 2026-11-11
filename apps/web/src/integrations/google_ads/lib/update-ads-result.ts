// apps/web/src/integrations/google_ads/lib/update-ads-result.ts

import { parseTextAssets } from "@/integrations/google_ads/lib/create-ads"
import { isEditOutcome, type EditOutcome } from "@/integrations/google_ads/lib/edit-outcomes"
import type { LiveCopy } from "@/integrations/google_ads/lib/update-ads"
import { isNonEmptyString, isRecord } from "@/lib/guards"

export type AdOutcomeRow = {
  adGroupName: string
  // Read back after the change; null when the read failed or nothing changed.
  after: LiveCopy | null
  approvalStatus: string | null
  before: LiveCopy | null
  campaignName: string
  errorCode: string | null
  message: string | null
  name: string
  outcome: EditOutcome
  requested: LiveCopy | null
  reviewStatus: string | null
}

export type UpdateAdsResult = { accountId: string; rows: AdOutcomeRow[] }

function nullableText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null
}

function copy(value: unknown): LiveCopy | null | undefined {
  if (value === null || value === undefined) return null
  if (!isRecord(value)) return undefined
  const headlines = parseTextAssets(value["headlines"])
  const descriptions = parseTextAssets(value["descriptions"])
  if (headlines === null || descriptions === null) return undefined
  return {
    descriptions,
    finalUrl: nullableText(value["final_url"]),
    headlines,
    path1: nullableText(value["path1"]),
    path2: nullableText(value["path2"]),
  }
}

function parseAd(raw: unknown): AdOutcomeRow | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["name"])) return null
  const outcome = raw["outcome"]
  const before = copy(raw["before"])
  const after = copy(raw["after"])
  const requested = copy(raw["requested"])
  if (
    !isEditOutcome(outcome) ||
    before === undefined ||
    after === undefined ||
    requested === undefined
  )
    return null
  return {
    adGroupName: nullableText(raw["ad_group_name"]) ?? "",
    after,
    approvalStatus: nullableText(raw["approval_status"]),
    before,
    campaignName: nullableText(raw["campaign_name"]) ?? "",
    errorCode: nullableText(raw["error_code"]),
    message: nullableText(raw["message"]),
    name: raw["name"],
    outcome,
    requested,
    reviewStatus: nullableText(raw["review_status"]),
  }
}

export function parseUpdateAdsResult(raw: unknown): UpdateAdsResult | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["account_id"]) || !Array.isArray(raw["ads"]))
    return null
  const rows = raw["ads"].map(parseAd)
  if (rows.some((row) => row === null)) return null
  return { accountId: raw["account_id"], rows: rows.filter((row) => row !== null) }
}

/** A changed ad that Google is still reviewing. */
export function inReview(row: AdOutcomeRow): boolean {
  return row.outcome === "updated" && row.reviewStatus === "REVIEW_IN_PROGRESS"
}

function texts(copy: LiveCopy | null): string[] {
  if (copy === null) return []
  return [
    ...copy.headlines.map((item) => item.text),
    ...copy.descriptions.map((item) => item.text),
    ...[copy.path1, copy.path2].filter((item) => item !== null).map((item) => `/${item}`),
    ...(copy.finalUrl ? [copy.finalUrl] : []),
  ]
}

/** What the edit took out of the ad and put in, as two short lines. */
export function changeLines(
  before: LiveCopy | null,
  after: LiveCopy | null
): { before: string; after: string } {
  if (JSON.stringify(before) === JSON.stringify(after)) return { after: "No change", before: "—" }
  const was = texts(before)
  const now = texts(after)
  const gone = was.filter((item) => !now.includes(item))
  const added = now.filter((item) => !was.includes(item))
  if (gone.length === 0 && added.length === 0)
    return { after: "Pins changed", before: "Pins changed" }
  return { after: added.join(" · ") || "—", before: gone.join(" · ") || "—" }
}
