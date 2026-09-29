// apps/web/src/integrations/google_ads/lib/labels.ts

import { googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

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
