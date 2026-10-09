// apps/web/src/integrations/meta_ads/lib/automatic-changes.ts

import { isNonEmptyString, isOneOf, isRecord, isStringArray } from "@/lib/guards"

export type AdFormat = "image" | "video" | "carousel"
type ChangeGroup = "media" | "text" | "added"

export type AutomaticChange = {
  key: string
  label: string
  description: string
  group: ChangeGroup
  aiGenerated: boolean
  formats: AdFormat[]
}

export const AD_FORMATS: ReadonlySet<AdFormat> = new Set(["image", "video", "carousel"])
export const CHANGE_GROUPS: readonly ChangeGroup[] = ["media", "text", "added"]
const GROUPS: ReadonlySet<ChangeGroup> = new Set(CHANGE_GROUPS)
const FORMAT_NAMES: Record<AdFormat, string> = {
  image: "image ads",
  video: "video ads",
  carousel: "carousels",
}

export const CHANGE_GROUP_TITLES: Record<ChangeGroup, string> = {
  media: "Changes to Images and Video",
  text: "Changes to Text",
  added: "Content Meta Adds",
}

// The server's catalogue is the one list of what Meta can change and how each is sent.
export function parseAutomaticChanges(value: unknown): AutomaticChange[] | null {
  if (!Array.isArray(value)) return null
  const changes: AutomaticChange[] = []
  for (const item of value) {
    if (
      !isRecord(item) ||
      !isNonEmptyString(item["key"]) ||
      !isNonEmptyString(item["label"]) ||
      typeof item["description"] !== "string" ||
      !isOneOf(GROUPS, item["group"]) ||
      typeof item["ai_generated"] !== "boolean" ||
      !isStringArray(item["formats"])
    )
      return null
    changes.push({
      key: item["key"],
      label: item["label"],
      description: item["description"],
      group: item["group"],
      aiGenerated: item["ai_generated"],
      formats: item["formats"].filter((format) => isOneOf(AD_FORMATS, format)),
    })
  }
  return changes
}

/** Names the formats in the call that a change can't apply to, for example "Doesn't apply to carousels". */
export function unappliedFormatsNote(
  change: AutomaticChange,
  used: ReadonlySet<AdFormat>
): string | null {
  const missing = [...used].filter((format) => !change.formats.includes(format))
  if (missing.length === 0) return null
  if (missing.length === used.size) return "Doesn't apply to any of these ads."
  return `Doesn't apply to ${missing.map((format) => FORMAT_NAMES[format]).join(" or ")}.`
}

export function hasAiGeneratedChange(
  changes: readonly AutomaticChange[],
  enabled: readonly string[]
): boolean {
  return changes.some((change) => change.aiGenerated && enabled.includes(change.key))
}
