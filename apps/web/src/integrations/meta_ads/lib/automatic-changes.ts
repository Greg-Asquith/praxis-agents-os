// apps/web/src/integrations/meta_ads/lib/automatic-changes.ts

import { isNonEmptyString, isOneOf, isRecord, isStringArray } from "@/lib/guards"

export type AdFormat = "image" | "video" | "carousel" | "existing_post"
type ChangeGroup = "media" | "text" | "added"

export type AutomaticChange = {
  key: string
  label: string
  description: string
  group: ChangeGroup
  aiGenerated: boolean
  formats: AdFormat[]
}

export const AD_FORMATS: ReadonlySet<AdFormat> = new Set([
  "image",
  "video",
  "carousel",
  "existing_post",
])
export const CHANGE_GROUPS: readonly ChangeGroup[] = ["media", "text", "added"]
const GROUPS: ReadonlySet<ChangeGroup> = new Set(CHANGE_GROUPS)
const TAGGED_FORMATS = [
  ["image", "Image"],
  ["video", "Video"],
  ["carousel", "Carousel"],
] as const

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

/** Names the formats a change applies to, for example "Video Ads"; null when it applies to all. */
export function formatTag(change: AutomaticChange): string | null {
  const names = TAGGED_FORMATS.filter(([format]) => change.formats.includes(format))
  return names.length === 0 || names.length === TAGGED_FORMATS.length
    ? null
    : `${names.map(([, name]) => name).join(", ")} Ads`
}

export function hasAiGeneratedChange(
  changes: readonly AutomaticChange[],
  enabled: readonly string[]
): boolean {
  return changes.some((change) => change.aiGenerated && enabled.includes(change.key))
}
