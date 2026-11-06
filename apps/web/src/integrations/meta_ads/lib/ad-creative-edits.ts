// apps/web/src/integrations/meta_ads/lib/ad-creative-edits.ts

import { parseCreateAdsArgs, type CreateAdsArgs } from "@/integrations/meta_ads/lib/create-ads-args"
import { isNonEmptyString, isRecord, isStringArray } from "@/lib/guards"

export type CreativeField =
  | "primary_text"
  | "headline"
  | "description"
  | "link"
  | "call_to_action"
  | "url_tags"
  | "media"
  | "vertical_media"
  | "thumbnail"
  | "cards"
  | "post"
  | "automatic_changes"

// In the order the tool lists them.
const FIELDS: readonly { key: CreativeField; title: string }[] = [
  { key: "primary_text", title: "Primary Text" },
  { key: "headline", title: "Headline" },
  { key: "description", title: "Description" },
  { key: "link", title: "Website Link" },
  { key: "call_to_action", title: "Button" },
  { key: "url_tags", title: "URL Tags" },
  { key: "media", title: "Media" },
  { key: "vertical_media", title: "Vertical Version" },
  { key: "thumbnail", title: "Thumbnail" },
  { key: "cards", title: "Carousel Cards" },
  { key: "post", title: "Post" },
  { key: "automatic_changes", title: "Advanced Settings" },
]
// Parts the card edits in the ad editor; automatic changes stay as the agent proposed.
const CONTENT_FIELDS = FIELDS.map((field) => field.key).filter((key) => key !== "automatic_changes")
// Parts that can be removed, which the tool reads as "none".
const REMOVABLE: ReadonlySet<CreativeField> = new Set(["description", "url_tags", "vertical_media"])

/** The ad's live creative, as the server read it for the card. */
export type CreativeCheck = {
  content: Record<string, unknown>
  adSet: Record<string, unknown> | null
  pageId: string | null
  pageName: string | null
  changed: CreativeField[]
  automaticChanges: string[]
  buttons: string[]
  notes: string[]
}

const FIELD_KEYS: ReadonlySet<string> = new Set(FIELDS.map((field) => field.key))

export function isCreativeField(value: string): value is CreativeField {
  return FIELD_KEYS.has(value)
}

export function creativeFieldTitle(key: CreativeField): string {
  return FIELDS.find((field) => field.key === key)?.title ?? key
}

export function parseCreativeCheck(value: unknown): CreativeCheck | null {
  if (!isRecord(value) || !isRecord(value["content"])) return null
  const text = (key: string) => (isNonEmptyString(value[key]) ? value[key] : null)
  const list = (key: string) => (isStringArray(value[key]) ? value[key] : [])
  return {
    content: value["content"],
    adSet: isRecord(value["ad_set"]) ? value["ad_set"] : null,
    pageId: text("page_id"),
    pageName: text("page_name"),
    changed: list("changed").filter(isCreativeField),
    automaticChanges: list("automatic_changes"),
    buttons: list("buttons"),
    notes: list("notes"),
  }
}

/** The creative after the change: the live content with each requested part applied. */
export function creativeAfter(
  check: CreativeCheck,
  changes: Record<string, unknown>
): Record<string, unknown> {
  const removed = new Set<string>(CONTENT_FIELDS.filter((key) => changes[key] === "none"))
  const after = Object.fromEntries(
    Object.entries(check.content).filter(([key]) => !removed.has(key))
  )
  for (const key of CONTENT_FIELDS)
    if (Object.hasOwn(changes, key) && changes[key] !== "none") after[key] = changes[key]
  return after
}

/** The `creative` argument for an edited ad: each part that differs from the live one. */
export function creativeChanges(
  check: CreativeCheck,
  edited: Record<string, unknown>,
  proposed: Record<string, unknown>
): Record<string, unknown> {
  const changes: Record<string, unknown> = {}
  for (const key of CONTENT_FIELDS) {
    const before = check.content[key]
    const after = edited[key]
    if (sameValue(before, after)) continue
    if (after === undefined || after === null) {
      if (REMOVABLE.has(key)) changes[key] = "none"
    } else changes[key] = after
  }
  if (Object.hasOwn(proposed, "automatic_changes"))
    changes["automatic_changes"] = proposed["automatic_changes"]
  return changes
}

/** The parts this change sets, in the tool's order. */
export function changedFields(changes: Record<string, unknown>): CreativeField[] {
  return FIELDS.map((field) => field.key).filter((key) => Object.hasOwn(changes, key))
}

/** Compares media and posts by what they are, not by the label the card shows. */
function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(identity(left)) === JSON.stringify(identity(right))
}

function identity(value: unknown): unknown {
  if (value === null) return undefined
  if (Array.isArray(value)) return value.map(identity)
  if (!isRecord(value)) return value
  if (value["entity_kind"] === "meta_ads_media" || value["entity_kind"] === "meta_ads_post")
    return [value["image_hash"], value["video_id"], value["post_id"]]
  if (value["entity_kind"] === "file") return ["file", value["entity_id"]]
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .flatMap((key) => (value[key] == null ? [] : [[key, identity(value[key])]]))
  )
}

/** A key-order-free form of a value, to tell whether the card still shows what was checked. */
export function stableJson(value: unknown): string {
  return JSON.stringify(identity(value) ?? null)
}

/** Builds the ad editor's model for one ad: its name, ad set, Page, and creative after the change. */
export function creativeEditorArgs({
  accountId,
  after,
  catalogue,
  check,
  name,
}: {
  accountId: string
  after: Record<string, unknown>
  catalogue: unknown
  check: CreativeCheck
  name: string
}): CreateAdsArgs | null {
  const adSet = check.adSet ?? { adset_id: "ad-set", label: "This ad's ad set" }
  return parseCreateAdsArgs({
    ads: [{ ...after, name, ad_sets: [adSet] }],
    page: { label: check.pageName ?? "Your Page", page_id: check.pageId },
    automatic_changes: check.automaticChanges,
    _account: { account_id: accountId },
    _automatic_change_catalogue: catalogue,
    _buttons: { website: check.buttons, app: check.buttons },
  })
}

/** Why the edited creative can't be sent, or null; the tool takes library media only. */
export function creativeMediaProblem(after: Record<string, unknown>): string | null {
  const media = [after["media"], after["vertical_media"], after["thumbnail"]]
  for (const card of Array.isArray(after["cards"]) ? after["cards"] : [])
    if (isRecord(card)) media.push(card["media"], card["thumbnail"])
  return media.some((item) => isRecord(item) && item["entity_kind"] === "file")
    ? "Choose media from the ad account's library. To use a workspace File, ask the agent to upload it first."
    : null
}
