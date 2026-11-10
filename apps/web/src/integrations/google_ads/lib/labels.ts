// apps/web/src/integrations/google_ads/lib/labels.ts

import { googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { isOneOf, isRecord } from "@/lib/guards"

const LABEL_NAME_MAX_LENGTH = 80
const LABEL_DESCRIPTION_MAX_LENGTH = 200
const LABEL_COLOR_PATTERN = /^#(?:[a-fA-F0-9]{6}|[a-fA-F0-9]{3})$/

export type GoogleAdsLabelDraft = {
  backgroundColor: string | null
  description: string | null
  name: string
}

function optionalText(value: unknown): string | null | undefined {
  if (value == null) return null
  return typeof value === "string" ? value.trim() || null : undefined
}

// Mirrors the server draft normalisation so approval previews match what is sent.
function parseLabelDraft(value: unknown): GoogleAdsLabelDraft | null {
  if (!isRecord(value) || typeof value["name"] !== "string") return null
  const description = optionalText(value["description"])
  const backgroundColor = optionalText(value["background_color"])
  if (description === undefined || backgroundColor === undefined) return null
  return {
    name: value["name"].split(/\s+/).filter(Boolean).join(" "),
    description,
    backgroundColor,
  }
}

export function parseLabelDrafts(value: unknown): GoogleAdsLabelDraft[] | null {
  if (!Array.isArray(value) || value.length === 0) return null
  const drafts: GoogleAdsLabelDraft[] = []
  for (const item of value) {
    const draft = parseLabelDraft(item)
    if (draft === null) return null
    drafts.push(draft)
  }
  return drafts
}

export function labelDraftsValidationError(drafts: readonly GoogleAdsLabelDraft[]): string | null {
  if (drafts.length > 50) return "Create at most 50 labels at a time."
  const names = new Set<string>()
  for (const draft of drafts) {
    if (!draft.name || codePointLength(draft.name) > LABEL_NAME_MAX_LENGTH)
      return `Give each label a name of ${String(LABEL_NAME_MAX_LENGTH)} characters or fewer.`
    if (draft.description && codePointLength(draft.description) > LABEL_DESCRIPTION_MAX_LENGTH)
      return `Keep each description to ${String(LABEL_DESCRIPTION_MAX_LENGTH)} characters or fewer.`
    if (draft.backgroundColor && !LABEL_COLOR_PATTERN.test(draft.backgroundColor))
      return "Use a colour such as #1A73E8, or leave it blank."
    const key = labelNameKey(draft.name)
    if (names.has(key)) return "Give each label a different name."
    names.add(key)
  }
  return null
}

export function labelColor(value: unknown): string | null {
  return typeof value === "string" && LABEL_COLOR_PATTERN.test(value) ? value : null
}

// Counts code points like the server's length limits, not UTF-16 units.
function codePointLength(value: string): number {
  return Array.from(value).length
}

// Locale-independent approximation of the server's casefold; the server stays authoritative.
export function labelNameKey(name: string): string {
  return name.toUpperCase().toLowerCase()
}

export function isLabelReference(value: unknown): boolean {
  return (
    isRecord(value) &&
    value["entity_kind"] === "google_ads_label" &&
    googleAdsId(value["customer_id"]) !== null &&
    googleAdsId(value["label_id"]) !== null
  )
}

export type LabelTargetKind = "campaign" | "ad_group" | "keyword"

export const LABEL_TARGET_KINDS = ["campaign", "ad_group", "keyword"] as const

export const LABEL_TARGET_KIND_LABELS: Record<LabelTargetKind, string> = {
  campaign: "Campaign",
  ad_group: "Ad group",
  keyword: "Keyword",
}

type GoogleAdsLabelSelection = { color: string | null; labelId: string; name: string }

type GoogleAdsLabelTargetSelection = { id: string; kind: LabelTargetKind; name: string }

export type LabelAssociationArgs = {
  labels: GoogleAdsLabelSelection[]
  targets: GoogleAdsLabelTargetSelection[]
}

const TARGET_KIND_SET = new Set(LABEL_TARGET_KINDS)

function parseLabelSelection(value: unknown): GoogleAdsLabelSelection | null {
  if (!isLabelReference(value) || !isRecord(value)) return null
  const labelId = String(value["label_id"])
  const name = typeof value["label"] === "string" ? value["label"].trim() : ""
  return { labelId, name: name || labelId, color: labelColor(value["background_color"]) }
}

function parseTargetSelection(value: unknown): GoogleAdsLabelTargetSelection | null {
  if (!isRecord(value) || !isOneOf(TARGET_KIND_SET, value["kind"])) return null
  const kind = value["kind"]
  const reference = value[kind]
  if (!isRecord(reference)) return null
  const id = targetId(kind, reference)
  if (id === null) return null
  const name = typeof reference["label"] === "string" ? reference["label"].trim() : ""
  return { kind, id, name: name || id }
}

// Keyword IDs pair the ad group and criterion, matching the server's association identity.
function targetId(kind: LabelTargetKind, reference: Record<string, unknown>): string | null {
  if (kind === "campaign") return googleAdsId(reference["campaign_id"])
  if (kind === "ad_group") return googleAdsId(reference["ad_group_id"])
  const adGroupId = googleAdsId(reference["ad_group_id"])
  const criterionId = googleAdsId(reference["criterion_id"])
  return adGroupId && criterionId ? `${adGroupId}~${criterionId}` : null
}

export function parseLabelAssociationArgs(value: unknown): LabelAssociationArgs | null {
  if (!isRecord(value) || !Array.isArray(value["labels"]) || !Array.isArray(value["targets"]))
    return null
  const labels = uniqueSelections(value["labels"], parseLabelSelection, (item) => item.labelId)
  const targets = uniqueSelections(
    value["targets"],
    parseTargetSelection,
    (item) => `${item.kind}:${item.id}`
  )
  return labels?.length && targets?.length ? { labels, targets } : null
}

function uniqueSelections<Item>(
  values: unknown[],
  parse: (value: unknown) => Item | null,
  identity: (item: Item) => string
): Item[] | null {
  const items: Item[] = []
  const seen = new Set<string>()
  for (const value of values) {
    const item = parse(value)
    if (item === null || seen.has(identity(item))) return null
    seen.add(identity(item))
    items.push(item)
  }
  return items
}
