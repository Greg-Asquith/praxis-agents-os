// apps/web/src/integrations/meta_ads/lib/copy-ads.ts

import { AD_FORMATS, type AdFormat } from "@/integrations/meta_ads/lib/automatic-changes"
import {
  parseAdSets,
  STATUSES,
  type AdSetInfo,
  type AdStatus,
  type PreviewMedia,
} from "@/integrations/meta_ads/lib/create-ads-args"
import { parseAdOutcomeFields, type AdOutcomeFields } from "@/integrations/meta_ads/lib/ad-outcome"
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
  // The ad set the source ad is in, which a copy can't go into.
  sourceAdSetId: string | null
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
  if (!isRecord(value) || !Array.isArray(value["copies"])) return null
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
    // An ad set picked on the card isn't hydrated yet, so its own reference stands in.
    adSets: parseAdSets(
      value["_ad_sets"],
      rawCopies.map((copy) => ({ ad_sets: [copy["ad_set"]] }))
    ),
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
    sourceAdSetId: stringValue(ad["adset_id"]),
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

type CopyEdit =
  | { name: string }
  | { status: AdStatus }
  | { adSet: Record<string, unknown> }
  | { remove: true }
  // Adds a copy of the same source ad into another ad set, paused.
  | { copyInto: Record<string, unknown> }

/** The `copies` argument after one edit; a blank name goes back to the source's name. */
export function editCopy(
  args: CopyAdsArgs,
  index: number,
  edit: CopyEdit
): Record<string, unknown>[] {
  return args.rawCopies.flatMap((raw, position) => {
    if (position !== index) return [raw]
    if ("remove" in edit) return []
    if ("copyInto" in edit) return [raw, { ad: raw["ad"], ad_set: edit.copyInto, status: "paused" }]
    if ("adSet" in edit) return [{ ...raw, ad_set: edit.adSet }]
    if ("status" in edit) return [{ ...raw, status: edit.status }]
    const { name: _previous, ...rest } = raw
    return [edit.name.trim() ? { ...rest, name: edit.name } : rest]
  })
}

/** Blocks approval when a copy has no valid place or two copies would clash. */
export function copyAdsProblem(args: CopyAdsArgs | null): string | null {
  if (!args) return null
  if (args.copies.length === 0) return "Keep at least one copy, or decline this request."
  const places = new Set<string>()
  const names = new Set<string>()
  for (const copy of args.copies) {
    if (copy.adSetId === copy.sourceAdSetId)
      return "Copy each ad into a different ad set from the one it's already in."
    const place = `${copy.adId}:${copy.adSetId}`
    if (places.has(place)) return "Copy each ad into each ad set only once."
    places.add(place)
    const name = `${copy.adSetId}:${(copy.name ?? sourceName(copy)).trim().toLowerCase()}`
    if (names.has(name)) return "Give copies in the same ad set different names before approving."
    names.add(name)
  }
  return null
}

export function copySummary(args: CopyAdsArgs): string {
  const copies = args.copies.length
  const adSets = new Set(args.copies.map((copy) => copy.adSetId)).size
  return `Copy ${String(copies)} ${pluralize(copies, "ad")} into ${String(adSets)} ${pluralize(adSets, "ad set")}${args.accountName ? ` in ${args.accountName}` : ""}.`
}

type CopyOutcome = "copied" | "failed" | "unverified"
type CopiedAd = AdOutcomeFields & {
  sourceName: string | null
  pausedForAi: boolean
  outcome: CopyOutcome
}

export type CopyAdsResult = { accountId: string; copies: CopiedAd[] }

const OUTCOMES: ReadonlySet<CopyOutcome> = new Set(["copied", "failed", "unverified"])

export function parseCopyAdsResult(value: unknown): CopyAdsResult | null {
  if (!isRecord(value) || !isNonEmptyString(value["account_id"]) || !Array.isArray(value["copies"]))
    return null
  const copies: CopiedAd[] = []
  for (const item of value["copies"]) {
    const fields = isRecord(item) ? parseAdOutcomeFields(item) : null
    if (!fields || !isRecord(item) || !isOneOf(OUTCOMES, item["outcome"])) return null
    copies.push({
      ...fields,
      sourceName: stringValue(item["source_name"]),
      pausedForAi: item["paused_for_ai"] === true,
      outcome: item["outcome"],
    })
  }
  return { accountId: value["account_id"], copies }
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
