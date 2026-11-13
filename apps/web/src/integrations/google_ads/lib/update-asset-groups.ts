// apps/web/src/integrations/google_ads/lib/update-asset-groups.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { ParentRow } from "@/integrations/ads/components/parent-table"
import type { CancelCard } from "@/integrations/ads/lib/cancelled-rows"
import { collapseSpaces } from "@/integrations/ads/lib/keyword-notation"
import { groupedByParent } from "@/integrations/ads/lib/parent-rows"
import {
  accountsText,
  type GoogleAdsApprovalAccount,
  parseApprovalAccounts,
} from "@/integrations/google_ads/lib/accounts"
import {
  applyChangesLabel,
  approvalCountLine,
  changesBlock,
} from "@/integrations/google_ads/lib/copy"
import { characterCount } from "@/integrations/google_ads/lib/create-ads"
import { googleAdsId, textOrNull } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

export type GroupChangeKind =
  | "name"
  | "final_url"
  | "HEADLINE"
  | "LONG_HEADLINE"
  | "DESCRIPTION"
  | "MARKETING_IMAGE"
  | "SQUARE_MARKETING_IMAGE"
  | "PORTRAIT_MARKETING_IMAGE"
  | "YOUTUBE_VIDEO"
  | "search_theme"
  | "audience_signal"

export type ItemKind = Exclude<GroupChangeKind, "name" | "final_url">
type Action = "add" | "remove" | "set"
// `unchecked` waits for a check of an edit; `unavailable` is a check that gave no answer.
type RowState = "change" | "already_set" | "not_found" | "unchecked" | "unavailable"

export const TEXT_KINDS: readonly ItemKind[] = ["HEADLINE", "LONG_HEADLINE", "DESCRIPTION"]
export const IMAGE_KINDS: readonly ItemKind[] = [
  "MARKETING_IMAGE",
  "SQUARE_MARKETING_IMAGE",
  "PORTRAIT_MARKETING_IMAGE",
]
export const ITEM_KINDS: readonly ItemKind[] = [
  ...TEXT_KINDS,
  ...IMAGE_KINDS,
  "YOUTUBE_VIDEO",
  "search_theme",
  "audience_signal",
]
// Where each kind's items sit in `add_assets` and `remove_assets`.
const ASSET_LISTS: Partial<Record<ItemKind, string>> = {
  DESCRIPTION: "descriptions",
  HEADLINE: "headlines",
  LONG_HEADLINE: "long_headlines",
  MARKETING_IMAGE: "images",
  PORTRAIT_MARKETING_IMAGE: "images",
  SQUARE_MARKETING_IMAGE: "images",
  YOUTUBE_VIDEO: "videos",
}

export const GROUP_CHANGE_LABELS: Record<GroupChangeKind, string> = {
  DESCRIPTION: "Description",
  final_url: "Final URL",
  HEADLINE: "Headline",
  LONG_HEADLINE: "Long Headline",
  MARKETING_IMAGE: "Landscape Image",
  name: "Name",
  PORTRAIT_MARKETING_IMAGE: "Portrait Image",
  search_theme: "Search Theme",
  SQUARE_MARKETING_IMAGE: "Square Image",
  audience_signal: "Audience Signal",
  YOUTUBE_VIDEO: "Video",
}

const NOUNS: Record<ItemKind, string> = {
  DESCRIPTION: "description",
  HEADLINE: "headline",
  LONG_HEADLINE: "long headline",
  MARKETING_IMAGE: "landscape image",
  PORTRAIT_MARKETING_IMAGE: "portrait image",
  SQUARE_MARKETING_IMAGE: "square image",
  audience_signal: "audience",
  search_theme: "theme",
  YOUTUBE_VIDEO: "video",
}

// Google's minimum and maximum of each kind in one asset group, as the server checks them.
const LIMITS: Record<ItemKind, readonly [number, number]> = {
  DESCRIPTION: [2, 5],
  HEADLINE: [3, 15],
  LONG_HEADLINE: [1, 5],
  MARKETING_IMAGE: [1, 20],
  PORTRAIT_MARKETING_IMAGE: [0, 20],
  SQUARE_MARKETING_IMAGE: [1, 20],
  audience_signal: [0, 20],
  search_theme: [0, 25],
  YOUTUBE_VIDEO: [0, 15],
}
export const TEXT_LIMITS: Partial<Record<GroupChangeKind, number>> = {
  DESCRIPTION: 90,
  HEADLINE: 30,
  LONG_HEADLINE: 90,
  name: 255,
  search_theme: 80,
}
const MAX_GROUPS = 100

const UNAVAILABLE =
  "Google Ads couldn't check this. Check again, or ask the agent to prepare the change again."

export type GroupEntry = {
  customerId: string
  // The entry as received, so an edit keeps every reference field.
  entry: Record<string, unknown>
  // The asset group's resource name, which its check is keyed by.
  key: string
  label: string
}

type CheckRow = {
  action: Action
  before: string | null
  item: string | null
  problem: string | null
  row: string
  state: "change" | "already_set" | "not_found"
}

type GroupCheck =
  | { unavailable: true }
  | {
      unavailable: false
      campaignName: string | null
      name: string
      now: Partial<Record<ItemKind, number>>
      retail: boolean
      problem: string | null
      rows: CheckRow[]
    }

export type UpdateAssetGroupsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  checks: Map<string, GroupCheck>
  entries: GroupEntry[]
}

export type GroupChangeRow = {
  action: Action
  // The item as sent, so Undo can put it back.
  raw: unknown
  before: string | null
  campaignName: string | null
  cancelled: boolean
  editable: boolean
  id: string
  kind: GroupChangeKind
  label: string
  problem: string | null
  // The change's name within its group, as the server keys its check.
  row: string
  state: RowState
  targetKey: string
  targetName: string
  value: string
}

function parseEntry(value: unknown): GroupEntry | null {
  if (!isRecord(value) || !isRecord(value["asset_group"])) return null
  const reference = value["asset_group"]
  const customerId = googleAdsId(reference["customer_id"])
  const groupId = googleAdsId(reference["asset_group_id"])
  if (customerId === null || groupId === null) return null
  return {
    customerId,
    entry: value,
    key: `customers/${customerId}/assetGroups/${groupId}`,
    label: textOrNull(reference["label"]) ?? `Asset Group ${groupId}`,
  }
}

function parseCheckRow(value: unknown): CheckRow | null {
  if (!isRecord(value)) return null
  const { action, state } = value
  const row = textOrNull(value["row"])
  if (
    row === null ||
    (action !== "add" && action !== "remove" && action !== "set") ||
    (state !== "change" && state !== "already_set" && state !== "not_found")
  )
    return null
  return {
    action,
    before: textOrNull(value["before"]),
    item: textOrNull(value["item"]),
    problem: textOrNull(value["problem"]),
    row,
    state,
  }
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0
}

function parseCheck(value: unknown): GroupCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const now = isRecord(value["now"]) ? value["now"] : {}
  const rows = Array.isArray(value["rows"]) ? value["rows"] : []
  return {
    unavailable: false,
    campaignName: textOrNull(value["campaign_name"]),
    name: textOrNull(value["name"]) ?? "",
    now: Object.fromEntries(ITEM_KINDS.map((kind) => [kind, count(now[kind])])),
    retail: value["retail"] === true,
    problem: textOrNull(value["problem"]),
    rows: rows.flatMap((row) => parseCheckRow(row) ?? []),
  }
}

/** Reads `entries` with the trusted `_accounts` and `_checks` beside them; null when malformed. */
export function parseUpdateAssetGroupsArgs(value: unknown): UpdateAssetGroupsArgs | null {
  if (!isRecord(value) || !Array.isArray(value["entries"])) return null
  const entries = value["entries"].map(parseEntry)
  if (entries.some((entry) => entry === null)) return null
  const checks = isRecord(value["_checks"]) ? value["_checks"] : {}
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    checks: new Map(Object.entries(checks).map(([key, check]) => [key, parseCheck(check)])),
    entries: entries.filter((entry) => entry !== null),
  }
}

export function serializeEntries(entries: readonly GroupEntry[]): Record<string, unknown>[] {
  return entries.map((entry) => entry.entry)
}

/** The list one kind's items sit in, for adding or removing. */
function listOf(
  entry: Record<string, unknown>,
  action: "add" | "remove",
  kind: ItemKind
): unknown[] {
  const field = ASSET_LISTS[kind]
  const assets = entry[`${action}_assets`]
  const list =
    field === undefined
      ? entry[kind === "search_theme" ? `${action}_search_themes` : `${action}_audience_signals`]
      : isRecord(assets)
        ? assets[field]
        : undefined
  return Array.isArray(list) ? (list as unknown[]) : []
}

function withList(
  entry: Record<string, unknown>,
  action: "add" | "remove",
  kind: ItemKind,
  list: unknown[]
): Record<string, unknown> {
  const field = ASSET_LISTS[kind]
  if (field === undefined) {
    const key = kind === "search_theme" ? `${action}_search_themes` : `${action}_audience_signals`
    return { ...entry, [key]: list }
  }
  const key = `${action}_assets`
  const assets = isRecord(entry[key]) ? entry[key] : {}
  return { ...entry, [key]: { ...assets, [field]: list } }
}

type Item = { kind: ItemKind; label: string; raw: unknown; value: string }

/** An item of one kind's list, by the value the server keys it by; null when it isn't one. */
function itemOf(kind: ItemKind, raw: unknown): Item | null {
  if (typeof raw === "string") {
    const text = collapseSpaces(raw)
    return TEXT_KINDS.includes(kind) || kind === "search_theme"
      ? { kind, label: text, raw, value: text }
      : null
  }
  if (!isRecord(raw)) return null
  if (kind === "audience_signal") {
    const key = textOrNull(raw["key"])
    const audience = textOrNull(raw["kind"])
    return key && audience
      ? { kind, label: textOrNull(raw["name"]) ?? key, raw, value: `${audience}:${key}` }
      : null
  }
  const image = IMAGE_KINDS.includes(kind)
  if (image && raw["field_type"] !== kind) return null
  const asset = image ? raw["asset"] : raw
  if (!isRecord(asset)) return null
  const id = googleAdsId(asset["asset_id"])
  return id ? { kind, label: textOrNull(asset["label"]) ?? id, raw, value: id } : null
}

function items(entry: Record<string, unknown>, action: "add" | "remove", kind: ItemKind): Item[] {
  return listOf(entry, action, kind).flatMap((raw) => itemOf(kind, raw) ?? [])
}

function rowKey(action: Action, kind: GroupChangeKind, value: string): string {
  return action === "set" ? kind : `${kind}|${value}`
}

function rowId(targetKey: string, action: Action, row: string): string {
  return `${targetKey}|${action}|${row}`
}

type Requested = { action: Action; item: Item | null; kind: GroupChangeKind; value: string }

/** Every change the entry asks for, in the server's order. */
function requested(entry: Record<string, unknown>): Requested[] {
  const changes: Requested[] = []
  for (const kind of ["name", "final_url"] as const) {
    const value = textOrNull(entry[kind])
    if (value !== null) changes.push({ action: "set", item: null, kind, value })
  }
  for (const action of ["remove", "add"] as const)
    for (const kind of ITEM_KINDS)
      for (const item of items(entry, action, kind))
        changes.push({ action, item, kind, value: item.value })
  return changes
}

function sameEntry(a: GroupEntry | undefined, b: GroupEntry): boolean {
  return JSON.stringify(a?.entry) === JSON.stringify(b.entry)
}

function groupName(checked: UpdateAssetGroupsArgs, entry: GroupEntry): string {
  const check = checked.checks.get(entry.key)
  return check && !check.unavailable && check.name ? check.name : entry.label
}

/** A problem the card knows before Google answers, such as a headline over 30 characters. */
function localProblem(change: Requested): string | null {
  const limit = TEXT_LIMITS[change.kind]
  if (change.action === "remove" || limit === undefined) return null
  if (change.value.length === 0)
    return `Enter the ${GROUP_CHANGE_LABELS[change.kind].toLowerCase()}.`
  return characterCount(change.value) > limit
    ? `${GROUP_CHANGE_LABELS[change.kind]}s take at most ${String(limit)} characters.`
    : null
}

/** Every change, checked against what Google last answered for, then cancelled ones. */
export function groupChangeRows(
  args: UpdateAssetGroupsArgs,
  checked: UpdateAssetGroupsArgs,
  cancelled: readonly GroupChangeRow[] = []
): GroupChangeRow[] {
  const answered = new Map(checked.entries.map((entry) => [entry.key, entry]))
  const live = args.entries.flatMap((entry) => {
    // An edited group waits for a new check, so its old answers don't apply.
    const check = sameEntry(answered.get(entry.key), entry)
      ? (checked.checks.get(entry.key) ?? { unavailable: true as const })
      : null
    const known = check && !check.unavailable ? check : null
    const answers = new Map(known?.rows.map((row) => [`${row.action}|${row.row}`, row]))
    return requested(entry.entry).map((change): GroupChangeRow => {
      const row = rowKey(change.action, change.kind, change.value)
      const answer = answers.get(`${change.action}|${row}`)
      // A change Google gave no answer for can't be approved, as the server refuses it.
      const unavailable =
        check !== null && (check.unavailable || (known?.problem == null && !answer))
      return {
        action: change.action,
        before: answer?.before ?? null,
        campaignName: known?.campaignName ?? null,
        cancelled: false,
        editable:
          change.action !== "remove" &&
          !IMAGE_KINDS.includes(change.kind as ItemKind) &&
          change.kind !== "YOUTUBE_VIDEO" &&
          change.kind !== "audience_signal",
        id: rowId(entry.key, change.action, row),
        kind: change.kind,
        label: answer?.item ?? change.item?.label ?? change.value,
        problem:
          localProblem(change) ??
          (unavailable ? UNAVAILABLE : (known?.problem ?? answer?.problem ?? null)),
        raw: change.item?.raw ?? change.value,
        row,
        state: unavailable ? "unavailable" : (answer?.state ?? "unchecked"),
        targetKey: entry.key,
        targetName: groupName(checked, entry),
        value: change.value,
      }
    })
  })
  const held = new Set(live.map((row) => row.id))
  return [
    ...live,
    ...cancelled
      .filter((row) => !held.has(row.id))
      .map((row) => ({ ...row, cancelled: true, problem: null })),
  ]
}

function settled(row: GroupChangeRow): boolean {
  return row.state === "already_set" || row.state === "not_found"
}

export type GroupCounts = { apply: number; problems: number; total: number }

export function groupCounts(rows: readonly GroupChangeRow[]): GroupCounts {
  const live = rows.filter((row) => !row.cancelled)
  return {
    apply: live.filter((row) => row.problem === null && !settled(row)).length,
    problems: live.filter((row) => row.problem !== null).length,
    total: live.length,
  }
}

export type KindSummary = {
  adding: number
  after: number
  kind: ItemKind
  maximum: number
  minimum: number
  now: number
  removing: number
}

/** What one group holds of each kind now and once its live changes apply; null before a check.
 *
 * Lists the kinds the group holds, needs, or changes. Changes already in place or not there
 * change nothing. */
export function kindSummary(
  args: UpdateAssetGroupsArgs,
  rows: readonly GroupChangeRow[],
  targetKey: string
): KindSummary[] | null {
  const check = args.checks.get(targetKey)
  if (!check || check.unavailable) return null
  const live = rows.filter(
    (row) =>
      row.targetKey === targetKey &&
      !row.cancelled &&
      (row.state === "change" || row.state === "unchecked")
  )
  return ITEM_KINDS.flatMap((kind) => {
    const [limit, maximum] = LIMITS[kind]
    // A retail group may hold no assets of its own; the server applies that rule.
    const minimum = check.retail ? 0 : limit
    const now = check.now[kind] ?? 0
    const removing = live.filter((row) => row.kind === kind && row.action === "remove").length
    const adding = live.filter((row) => row.kind === kind && row.action === "add").length
    const touched = rows.some((row) => row.targetKey === targetKey && row.kind === kind)
    if (now === 0 && minimum === 0 && !touched) return []
    return [{ adding, after: now - removing + adding, kind, maximum, minimum, now, removing }]
  })
}

/** Why a kind's count after the changes is outside Google's limits, or null.
 *
 * As on the server, only removals answer to the minimum and only additions to the maximum. */
export function limitProblem(item: KindSummary): string | null {
  const label = `${GROUP_CHANGE_LABELS[item.kind]}s`
  if (item.removing > 0 && item.after < item.minimum)
    return `${label} would drop to ${String(item.after)}; Google needs ${String(item.minimum)}.`
  if (item.adding > 0 && item.after > item.maximum)
    return `${label} would reach ${String(item.after)}; Google allows ${String(item.maximum)}.`
  return null
}

function limitProblems(args: UpdateAssetGroupsArgs, rows: readonly GroupChangeRow[]): string[] {
  return args.entries.flatMap(
    (entry) => kindSummary(args, rows, entry.key)?.flatMap((item) => limitProblem(item) ?? []) ?? []
  )
}

/** What a group holds now, such as "4 headlines, 7 themes", or "". */
function nowText(now: Partial<Record<ItemKind, number>>): string {
  return ITEM_KINDS.flatMap((kind) => {
    const total = now[kind] ?? 0
    return total > 0 && kind !== "audience_signal" ? [approvalCountLine(total, NOUNS[kind])] : []
  }).join(", ")
}

/** One row per asset group, with what it holds now and what changes. */
export function groupParents(
  args: UpdateAssetGroupsArgs,
  rows: readonly GroupChangeRow[],
  showAccount: boolean
): ParentRow[] {
  return groupedByParent(rows, (row) => row.targetKey).map(({ items: all, key, live }) => {
    const check = args.checks.get(key)
    const known = check && !check.unavailable ? check : null
    const account = showAccount ? (args.accounts.get(key.split("/")[1] ?? "")?.label ?? null) : null
    return {
      cancelled: live.length === 0,
      context: [known?.campaignName ?? null, account].filter(Boolean).join(" · ") || null,
      key,
      name: all[0]?.targetName ?? key,
      problems: live.filter((row) => row.problem !== null).length,
      values: {
        changes: live.length,
        now: known ? nowText(known.now) : "",
      },
    }
  })
}

/** The entry without the row's change. */
function withoutRow(entry: Record<string, unknown>, row: GroupChangeRow): Record<string, unknown> {
  if (row.action === "set")
    return Object.fromEntries(Object.entries(entry).filter(([key]) => key !== row.kind))
  const kind = row.kind as ItemKind
  const kept = listOf(entry, row.action, kind).filter(
    (raw) => itemOf(kind, raw)?.value !== row.value
  )
  return withList(entry, row.action, kind, kept)
}

function changeCount(entry: Record<string, unknown>): number {
  return requested(entry).length
}

/** Takes rows out of the request; a group left with nothing leaves too, kept empty for Undo. */
export function cancelGroupChanges(
  args: UpdateAssetGroupsArgs,
  rows: readonly GroupChangeRow[],
  ids: ReadonlySet<string>
): { departed: GroupEntry[]; dropped: GroupChangeRow[]; entries: GroupEntry[] } {
  const dropped = rows.filter((row) => ids.has(row.id) && !row.cancelled)
  const departed: GroupEntry[] = []
  const entries = args.entries.flatMap((entry) => {
    const gone = dropped.filter((row) => row.targetKey === entry.key)
    if (gone.length === 0) return [entry]
    const next = { ...entry, entry: gone.reduce(withoutRow, entry.entry) }
    if (changeCount(next.entry) > 0) return [next]
    departed.push(next)
    return []
  })
  return { departed, dropped, entries }
}

/** The group with a cancelled change back in it. */
function withRow(entry: GroupEntry, row: GroupChangeRow): GroupEntry | null {
  const held = requested(entry.entry).some(
    (change) =>
      change.action === row.action && rowKey(change.action, change.kind, change.value) === row.row
  )
  if (held) return null
  if (row.action === "set") return { ...entry, entry: { ...entry.entry, [row.kind]: row.raw } }
  const kind = row.kind as ItemKind
  const list = listOf(entry.entry, row.action, kind)
  return { ...entry, entry: withList(entry.entry, row.action, kind, [...list, row.raw]) }
}

/** Puts `next` in place of the item the row adds, or sets the row's name or URL.
 *
 * `next` is the new text for text and themes, the audience as searched, or the image with
 * its new shape. */
export function editGroupChange(
  args: UpdateAssetGroupsArgs,
  row: GroupChangeRow,
  next: unknown
): GroupEntry[] {
  return args.entries.map((entry) => {
    if (entry.key !== row.targetKey) return entry
    if (row.action === "set") return { ...entry, entry: { ...entry.entry, [row.kind]: next } }
    const kind = row.kind as ItemKind
    const list = listOf(entry.entry, "add", kind).map((raw) =>
      itemOf(kind, raw)?.value === row.value ? next : raw
    )
    return { ...entry, entry: withList(entry.entry, "add", kind, list) }
  })
}

/** Adds one item of a kind to the group's additions; an item it already adds is left alone. */
export function addGroupItem(
  args: UpdateAssetGroupsArgs,
  targetKey: string,
  kind: ItemKind,
  raw: unknown
): GroupEntry[] {
  const added = itemOf(kind, raw)
  return args.entries.map((entry) => {
    if (entry.key !== targetKey || added === null) return entry
    const list = listOf(entry.entry, "add", kind)
    if (list.some((item) => itemOf(kind, item)?.value === added.value)) return entry
    return { ...entry, entry: withList(entry.entry, "add", kind, [...list, raw]) }
  })
}

/** What the server refuses whatever Google answers: the request's size. */
export function groupLimitProblems(args: UpdateAssetGroupsArgs): string[] {
  return args.entries.length > MAX_GROUPS
    ? [`One request can change at most ${String(MAX_GROUPS)} asset groups.`]
    : []
}

function localProblemCount(args: UpdateAssetGroupsArgs): number {
  return args.entries.flatMap((entry) => requested(entry.entry)).filter(localProblem).length
}

/** Whether Google can check the request; the server refuses one the card knows is wrong. */
export function canCheckGroups(args: UpdateAssetGroupsArgs): boolean {
  return groupLimitProblems(args).length === 0 && localProblemCount(args) === 0
}

/** True when the last check left a change without an answer. */
export function groupCheckIncomplete(checked: UpdateAssetGroupsArgs): boolean {
  return groupChangeRows(checked, checked).some((row) => row.state === "unavailable")
}

export function groupsNeedCheck(
  args: UpdateAssetGroupsArgs,
  checked: UpdateAssetGroupsArgs
): boolean {
  return (
    groupCheckIncomplete(checked) ||
    JSON.stringify(serializeEntries(args.entries)) !==
      JSON.stringify(serializeEntries(checked.entries))
  )
}

/** Why the request can't be approved yet, or null. */
export function assetGroupsBlock(
  args: UpdateAssetGroupsArgs | null,
  checked: UpdateAssetGroupsArgs
): string | null {
  if (args === null) return null
  const [limit] = groupLimitProblems(args)
  if (limit) return limit
  const local = localProblemCount(args)
  if (local > 0) return `Fix or cancel ${approvalCountLine(local, "change")} to continue.`
  const [limitText] = limitProblems(args, groupChangeRows(args, checked))
  if (limitText) return `${limitText} Fix or cancel changes to continue.`
  return changesBlock(
    groupCounts(groupChangeRows(args, checked)),
    groupsNeedCheck(args, checked),
    "These asset groups already look like this."
  )
}

export function assetGroupsApproveLabel(args: UpdateAssetGroupsArgs): string {
  return applyChangesLabel(groupCounts(groupChangeRows(args, args)).apply)
}

export function assetGroupsPrompt(args: UpdateAssetGroupsArgs): string {
  if (args.entries.length === 0) return "Nothing is left to change."
  const where = accountsText(
    args.accounts,
    args.entries.map((entry) => entry.customerId)
  )
  const [first] = args.entries
  const groups =
    args.entries.length === 1 && first
      ? groupName(args, first)
      : approvalCountLine(args.entries.length, "asset group")
  const campaigns = new Set(
    args.entries.flatMap((entry) => {
      const check = args.checks.get(entry.key)
      return check && !check.unavailable && check.campaignName ? [check.campaignName] : []
    })
  ).size
  const inCampaigns =
    args.entries.length > 1 && campaigns > 1
      ? ` in ${approvalCountLine(campaigns, "Performance Max campaign")}`
      : ""
  return `Change ${groups}${inCampaigns} in ${where}.`
}

export function assetGroupsDetails(args: UpdateAssetGroupsArgs | null): FanOutDetail[] {
  return args ? [{ label: "Asset Groups", value: String(args.entries.length) }] : []
}

function isRow(value: unknown): value is GroupChangeRow {
  return (
    isRecord(value) && typeof value["id"] === "string" && typeof value["targetKey"] === "string"
  )
}

// How the shared cancelled-rows helpers read and restore this card's changes.
export const GROUP_CANCEL_CARD: CancelCard<GroupEntry, GroupChangeRow> = {
  isRow,
  parseEntry,
  serializeEntries,
  withRow,
}
