// apps/web/src/integrations/google_ads/lib/negative-keywords.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { ParentRow } from "@/integrations/ads/components/parent-table"
import {
  collapseSpaces,
  type KeywordMatchType,
  type PastedKeyword,
} from "@/integrations/ads/lib/keyword-notation"
import type { CancelCard } from "@/integrations/ads/lib/cancelled-rows"
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
import { googleAdsId, textOrNull } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

export type NegativeTargetKind = "campaign" | "ad_group" | "list" | "new_list"
type RowItem = "keyword" | "campaign"
type RowAction = "add" | "remove"
type RowState = "change" | "already_set" | "not_found" | "unchecked"

export const MATCH_TYPES: readonly KeywordMatchType[] = ["EXACT", "PHRASE", "BROAD"]

export const MATCH_TYPE_LABELS: Record<KeywordMatchType, string> = {
  BROAD: "Broad",
  EXACT: "Exact",
  PHRASE: "Phrase",
}

export const TARGET_KIND_LABELS: Record<NegativeTargetKind, string> = {
  ad_group: "Ad Group",
  campaign: "Campaign",
  list: "List",
  new_list: "New List",
}

type CampaignRef = {
  campaignId: string
  key: string
  label: string
  value: Record<string, unknown>
}

export type NegativeEntry = {
  add: PastedKeyword[]
  apply: CampaignRef[]
  customerId: string
  // The entry as received, so an edit keeps every reference field.
  entry: Record<string, unknown>
  // The server's name for the target, which its check is keyed by.
  key: string
  kind: NegativeTargetKind
  label: string
  remove: PastedKeyword[]
  removeFrom: CampaignRef[]
}

type CheckRow = {
  action: RowAction
  item: RowItem
  key: string
  problem: string | null
  state: Exclude<RowState, "unchecked">
}

type TargetCheck =
  | { unavailable: true }
  | { unavailable: false; name: string; problem: string | null; rows: CheckRow[] }

export type UpdateNegativeKeywordsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  checks: Map<string, TargetCheck>
  entries: NegativeEntry[]
}

export type NegativeRow = {
  action: RowAction
  // Kept for Undo: the campaign's reference, when the row is a campaign.
  campaign: CampaignRef | null
  cancelled: boolean
  id: string
  item: RowItem
  matchType: KeywordMatchType | null
  name: string
  problem: string | null
  state: RowState
  targetKey: string
  targetKind: NegativeTargetKind
  targetName: string
}

export type NegativeCounts = {
  add: number
  alreadySet: number
  apply: number
  cancelled: number
  notFound: number
  problems: number
  remove: number
  total: number
}

const UNAVAILABLE =
  "Google Ads couldn't check this. Check again, or ask the agent to prepare the change again."

function parseKeywords(value: unknown): PastedKeyword[] | null {
  if (value === undefined) return []
  if (!Array.isArray(value)) return null
  const keywords: PastedKeyword[] = []
  for (const item of value) {
    if (!isRecord(item)) return null
    const matchType = item["match_type"]
    const keyword = textOrNull(item["text"])
    if (keyword === null || !MATCH_TYPES.includes(matchType as KeywordMatchType)) return null
    keywords.push({ matchType: matchType as KeywordMatchType, text: collapseSpaces(keyword) })
  }
  return keywords
}

function parseCampaigns(value: unknown): CampaignRef[] | null {
  if (value === undefined) return []
  if (!Array.isArray(value)) return null
  const campaigns: CampaignRef[] = []
  for (const item of value) {
    if (!isRecord(item)) return null
    const customerId = googleAdsId(item["customer_id"])
    const campaignId = googleAdsId(item["campaign_id"])
    if (customerId === null || campaignId === null) return null
    campaigns.push({
      campaignId,
      key: `customers/${customerId}/campaigns/${campaignId}`,
      label: textOrNull(item["label"]) ?? `Campaign ${campaignId}`,
      value: item,
    })
  }
  return campaigns
}

// The reference field each kind keeps its target in, with the ID it carries.
const TARGET_FIELDS = {
  ad_group: { collection: "adGroups", field: "ad_group", id: "ad_group_id" },
  campaign: { collection: "campaigns", field: "campaign", id: "campaign_id" },
  list: { collection: "sharedSets", field: "negative_list", id: "shared_set_id" },
} as const

function parseTarget(
  value: Record<string, unknown>,
  kind: NegativeTargetKind,
  apply: readonly CampaignRef[]
): { customerId: string; key: string; label: string } | null {
  if (kind === "new_list") {
    const name = textOrNull(value["new_list"])
    const customerId = apply[0]?.key.split("/")[1]
    if (name === null || !customerId) return null
    return {
      customerId,
      key: `customers/${customerId}/newSharedSets/${collapseSpaces(name).toLowerCase()}`,
      label: collapseSpaces(name),
    }
  }
  const { collection, field, id } = TARGET_FIELDS[kind]
  const reference = value[field]
  if (!isRecord(reference)) return null
  const customerId = googleAdsId(reference["customer_id"])
  const targetId = googleAdsId(reference[id])
  if (customerId === null || targetId === null) return null
  return {
    customerId,
    key: `customers/${customerId}/${collection}/${targetId}`,
    label: textOrNull(reference["label"]) ?? `${TARGET_KIND_LABELS[kind]} ${targetId}`,
  }
}

function parseEntry(value: unknown): NegativeEntry | null {
  if (!isRecord(value)) return null
  const kind = value["kind"]
  if (kind !== "campaign" && kind !== "ad_group" && kind !== "list" && kind !== "new_list")
    return null
  const add = parseKeywords(value["add"])
  const remove = parseKeywords(value["remove"])
  const apply = parseCampaigns(value["apply_to_campaigns"])
  const removeFrom = parseCampaigns(value["remove_from_campaigns"])
  if (add === null || remove === null || apply === null || removeFrom === null) return null
  const target = parseTarget(value, kind, apply)
  return target ? { ...target, add, apply, entry: value, kind, remove, removeFrom } : null
}

function parseCheckRow(value: unknown): CheckRow | null {
  if (!isRecord(value)) return null
  const { action, item, state } = value
  const key = textOrNull(value["key"])
  if (
    key === null ||
    (action !== "add" && action !== "remove") ||
    (item !== "keyword" && item !== "campaign") ||
    (state !== "change" && state !== "already_set" && state !== "not_found")
  )
    return null
  return { action, item, key, problem: textOrNull(value["problem"]), state }
}

function parseCheck(value: unknown): TargetCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const rows = Array.isArray(value["rows"]) ? value["rows"] : []
  return {
    unavailable: false,
    name: textOrNull(value["name"]) ?? "",
    problem: textOrNull(value["problem"]),
    rows: rows.flatMap((row) => parseCheckRow(row) ?? []),
  }
}

/** Reads `entries` with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseNegativeKeywordsArgs(value: unknown): UpdateNegativeKeywordsArgs | null {
  if (!isRecord(value) || !Array.isArray(value["entries"])) return null
  const entries: NegativeEntry[] = []
  for (const item of value["entries"]) {
    const entry = parseEntry(item)
    if (entry === null) return null
    entries.push(entry)
  }
  const checks = isRecord(value["_checks"]) ? value["_checks"] : {}
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    checks: new Map(Object.entries(checks).map(([key, check]) => [key, parseCheck(check)])),
    entries,
  }
}

/** How the server names a row within its target. */
function rowKey(
  item: RowItem,
  name: string,
  matchType: KeywordMatchType | null,
  campaign?: string
) {
  return item === "keyword"
    ? `${matchType ?? ""}:${collapseSpaces(name).toLowerCase()}`
    : (campaign ?? "")
}

function targetName(args: UpdateNegativeKeywordsArgs, entry: NegativeEntry): string {
  const check = args.checks.get(entry.key)
  return check && !check.unavailable && check.name ? check.name : entry.label
}

function entryRows(entry: NegativeEntry, name: string, check: TargetCheck | undefined) {
  const shown = new Map(
    check && !check.unavailable
      ? check.rows.map((row) => [`${row.item}|${row.action}|${row.key}`, row])
      : []
  )
  const row = (
    item: RowItem,
    action: RowAction,
    label: string,
    matchType: KeywordMatchType | null,
    campaign: CampaignRef | null
  ): NegativeRow => {
    const key = rowKey(item, label, matchType, campaign?.key)
    const checked = shown.get(`${item}|${action}|${key}`)
    const problem =
      check === undefined
        ? null
        : check.unavailable
          ? UNAVAILABLE
          : (check.problem ?? checked?.problem ?? null)
    return {
      action,
      campaign,
      cancelled: false,
      id: `${entry.key}|${item}|${action}|${key}`,
      item,
      matchType,
      name: label,
      problem,
      state: checked?.state ?? "unchecked",
      targetKey: entry.key,
      targetKind: entry.kind,
      targetName: name,
    }
  }
  return [
    ...entry.remove.map((keyword) =>
      row("keyword", "remove", keyword.text, keyword.matchType, null)
    ),
    ...entry.add.map((keyword) => row("keyword", "add", keyword.text, keyword.matchType, null)),
    ...entry.removeFrom.map((campaign) =>
      row("campaign", "remove", campaign.label, null, campaign)
    ),
    ...entry.apply.map((campaign) => row("campaign", "add", campaign.label, null, campaign)),
  ]
}

/** Every change in the request, checked against what Google last answered for, then cancelled ones. */
export function negativeRows(
  args: UpdateNegativeKeywordsArgs,
  checked: UpdateNegativeKeywordsArgs,
  cancelled: readonly NegativeRow[] = []
): NegativeRow[] {
  const answered = new Map(checked.entries.map((entry) => [entry.key, entry]))
  const live = args.entries.flatMap((entry) => {
    const same = JSON.stringify(answered.get(entry.key)?.entry) === JSON.stringify(entry.entry)
    // An edited target waits for a new check, so its old answers don't apply.
    const check = same ? checked.checks.get(entry.key) : undefined
    return entryRows(entry, targetName(checked, entry), check)
  })
  const held = new Set(live.map((row) => row.id))
  return [
    ...live,
    ...cancelled
      .filter((row) => !held.has(row.id))
      .map((row) => ({ ...row, cancelled: true, problem: null })),
  ]
}

export function negativeCounts(rows: readonly NegativeRow[]): NegativeCounts {
  const live = rows.filter((row) => !row.cancelled)
  const count = (match: (row: NegativeRow) => boolean) => live.filter(match).length
  return {
    // Negatives this request adds, as the searches it blocks.
    add: count(
      (row) =>
        row.item === "keyword" &&
        row.action === "add" &&
        row.problem === null &&
        row.state !== "already_set"
    ),
    alreadySet: count((row) => row.state === "already_set"),
    // A blocked change has to be fixed or cancelled, so it doesn't count towards what applies.
    apply: count(
      (row) => row.problem === null && (row.state === "change" || row.state === "unchecked")
    ),
    cancelled: rows.length - live.length,
    notFound: count((row) => row.state === "not_found"),
    problems: count((row) => row.problem !== null),
    remove: count((row) => row.action === "remove"),
    total: live.length,
  }
}

function keywordEntries(keywords: readonly PastedKeyword[]) {
  return keywords.map((keyword) => ({ match_type: keyword.matchType, text: keyword.text }))
}

function withChanges(
  entry: NegativeEntry,
  next: {
    add?: PastedKeyword[]
    apply?: CampaignRef[]
    remove?: PastedKeyword[]
    removeFrom?: CampaignRef[]
  }
): NegativeEntry | null {
  const fields: Record<string, unknown> = { ...entry.entry }
  // Only a list that changed is rewritten, so an untouched target keeps what Google checked.
  const set = (key: string, before: unknown[], after: unknown[] | undefined) => {
    if (after && JSON.stringify(after) !== JSON.stringify(before)) fields[key] = after
  }
  set("add", keywordEntries(entry.add), next.add && keywordEntries(next.add))
  if (entry.kind !== "new_list")
    set("remove", keywordEntries(entry.remove), next.remove && keywordEntries(next.remove))
  if (entry.kind === "list" || entry.kind === "new_list")
    set(
      "apply_to_campaigns",
      entry.apply.map((campaign) => campaign.value),
      next.apply?.map((campaign) => campaign.value)
    )
  if (entry.kind === "list")
    set(
      "remove_from_campaigns",
      entry.removeFrom.map((campaign) => campaign.value),
      next.removeFrom?.map((campaign) => campaign.value)
    )
  return parseEntry(fields)
}

/** Whether the server takes the entry: a new list needs keywords and a campaign. */
function isValid(entry: NegativeEntry): boolean {
  if (entry.kind === "new_list") return entry.add.length > 0 && entry.apply.length > 0
  return entry.add.length + entry.remove.length + entry.apply.length + entry.removeFrom.length > 0
}

function unique(keywords: readonly PastedKeyword[]): PastedKeyword[] {
  const seen = new Set<string>()
  return keywords.filter((keyword) => {
    const id = rowKey("keyword", keyword.text, keyword.matchType)
    if (seen.has(id)) return false
    seen.add(id)
    return true
  })
}

export type NegativeEdit = {
  // The entries to send, and rows that left the request with them, which Undo can restore.
  dropped: NegativeRow[]
  entries: NegativeEntry[]
}

/** Applies a change to each keyword row in `ids`, dropping a target the change leaves invalid.
 *
 * With `dropCampaigns`, campaign rows in `ids` leave the request too. */
function editRows(
  args: UpdateNegativeKeywordsArgs,
  rows: readonly NegativeRow[],
  ids: ReadonlySet<string>,
  change: (keyword: PastedKeyword) => PastedKeyword | null,
  dropCampaigns: boolean
): NegativeEdit {
  const dropped: NegativeRow[] = []
  const entries = args.entries.flatMap((entry) => {
    const mine = rows.filter((row) => row.targetKey === entry.key && !row.cancelled)
    const chosen = new Set(mine.filter((row) => ids.has(row.id)).map((row) => row.id))
    const id = (
      item: RowItem,
      action: RowAction,
      name: string,
      matchType: KeywordMatchType | null,
      campaign?: string
    ) => `${entry.key}|${item}|${action}|${rowKey(item, name, matchType, campaign)}`
    const edit = (action: RowAction, keywords: readonly PastedKeyword[]) =>
      unique(
        keywords.flatMap((keyword) =>
          chosen.has(id("keyword", action, keyword.text, keyword.matchType))
            ? (change(keyword) ?? [])
            : [keyword]
        )
      )
    const keep = (action: RowAction) => (campaign: CampaignRef) =>
      !dropCampaigns || !chosen.has(id("campaign", action, campaign.label, null, campaign.key))
    const next = withChanges(entry, {
      add: edit("add", entry.add),
      apply: entry.apply.filter(keep("add")),
      remove: edit("remove", entry.remove),
      removeFrom: entry.removeFrom.filter(keep("remove")),
    })
    if (next && isValid(next)) {
      const kept = new Set(entryRows(next, "", undefined).map((row) => row.id))
      dropped.push(...mine.filter((row) => chosen.has(row.id) && !kept.has(row.id)))
      return [next]
    }
    dropped.push(...mine)
    return []
  })
  return { dropped, entries }
}

/** Takes the rows out of the request; a target left with nothing it can send leaves too. */
export function cancelRows(
  args: UpdateNegativeKeywordsArgs,
  rows: readonly NegativeRow[],
  ids: ReadonlySet<string>
): NegativeEdit {
  return editRows(args, rows, ids, () => null, true)
}

export function setMatchType(
  args: UpdateNegativeKeywordsArgs,
  rows: readonly NegativeRow[],
  ids: ReadonlySet<string>,
  matchType: KeywordMatchType
): NegativeEdit {
  return editRows(args, rows, ids, (keyword) => ({ ...keyword, matchType }), false)
}

/** The target with a cancelled row back in it. */
function withRow(entry: NegativeEntry, row: NegativeRow): NegativeEntry | null {
  const keyword = row.matchType ? { matchType: row.matchType, text: row.name } : null
  return withChanges(entry, {
    add: row.action === "add" && keyword ? unique([...entry.add, keyword]) : entry.add,
    apply:
      row.action === "add" && row.campaign && !entry.apply.some((c) => c.key === row.campaign?.key)
        ? [...entry.apply, row.campaign]
        : entry.apply,
    remove: row.action === "remove" && keyword ? unique([...entry.remove, keyword]) : entry.remove,
    removeFrom:
      row.action === "remove" &&
      row.campaign &&
      !entry.removeFrom.some((c) => c.key === row.campaign?.key)
        ? [...entry.removeFrom, row.campaign]
        : entry.removeFrom,
  })
}

function linksText(rows: readonly NegativeRow[]): string | null {
  const count = (action: RowAction) =>
    rows.filter((row) => row.item === "campaign" && row.action === action).length
  const parts = [
    count("add") > 0 ? `${approvalCountLine(count("add"), "campaign")} start using it` : null,
    count("remove") > 0 ? `${approvalCountLine(count("remove"), "campaign")} stop using it` : null,
  ]
  return parts.filter((part) => part !== null).join(", ") || null
}

/** One row per campaign, ad group, or list the negatives change, in the order it first appears. */
export function negativeParents(
  rows: readonly NegativeRow[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>,
  showAccount: boolean
): ParentRow[] {
  return groupedByParent(rows, (row) => row.targetKey).map(({ items, key, live }) => {
    const first = items[0]
    const keywords = (action: RowAction) =>
      live.filter((row) => row.item === "keyword" && row.action === action).length
    const account = showAccount ? (accounts.get(key.split("/")[1] ?? "")?.label ?? null) : null
    return {
      cancelled: live.length === 0,
      context: [linksText(live), account].filter((part) => part !== null).join(" · ") || null,
      key,
      name: first?.targetName ?? key,
      problems: live.filter((row) => row.problem !== null).length,
      values: {
        add: keywords("add"),
        kind: first ? TARGET_KIND_LABELS[first.targetKind] : "",
        remove: keywords("remove"),
      },
    }
  })
}

/** Adds pasted keywords to each chosen target, leaving out ones it already lists. */
export type SearchableTargetKind = Exclude<NegativeTargetKind, "new_list">

// The entity lookup each target kind is searched with.
export const TARGET_ENTITY_KINDS: Record<SearchableTargetKind, string> = {
  ad_group: "google_ads_ad_group",
  campaign: "google_ads_campaign",
  list: "google_ads_shared_set",
}

/** A target the operator found by search, with nothing to change yet. */
export function targetEntry(
  kind: SearchableTargetKind,
  value: Record<string, unknown>
): NegativeEntry | null {
  return parseEntry({ kind, [TARGET_FIELDS[kind].field]: value })
}

/** Adds keywords to the chosen targets; a target not in the request joins it. */
export function addKeywords(
  args: UpdateNegativeKeywordsArgs,
  targets: readonly NegativeEntry[],
  keywords: readonly PastedKeyword[]
): NegativeEntry[] {
  const chosen = new Set(targets.map((target) => target.key))
  const held = new Set(args.entries.map((entry) => entry.key))
  const grow = (entry: NegativeEntry) => {
    const removing = new Set(entry.remove.map((k) => rowKey("keyword", k.text, k.matchType)))
    const add = unique([
      ...entry.add,
      ...keywords.filter((k) => !removing.has(rowKey("keyword", k.text, k.matchType))),
    ])
    return withChanges(entry, { add }) ?? entry
  }
  return [
    ...args.entries.map((entry) => (chosen.has(entry.key) ? grow(entry) : entry)),
    ...targets.filter((target) => !held.has(target.key)).map(grow),
  ]
}

export function addListCampaign(
  args: UpdateNegativeKeywordsArgs,
  targetKey: string,
  value: Record<string, unknown>
): NegativeEntry[] {
  const [campaign] = parseCampaigns([value]) ?? []
  return args.entries.map((entry) => {
    if (entry.key !== targetKey || !campaign) return entry
    const held = [...entry.apply, ...entry.removeFrom].some((item) => item.key === campaign.key)
    if (held || campaign.key.split("/")[1] !== entry.customerId) return entry
    return withChanges(entry, { apply: [...entry.apply, campaign] }) ?? entry
  })
}

export function serializeEntries(entries: readonly NegativeEntry[]): Record<string, unknown>[] {
  return entries.map((entry) => entry.entry)
}

export function needsCheck(
  args: UpdateNegativeKeywordsArgs,
  checked: UpdateNegativeKeywordsArgs
): boolean {
  return (
    [...checked.checks.values()].some((check) => check.unavailable) ||
    JSON.stringify(serializeEntries(args.entries)) !==
      JSON.stringify(serializeEntries(checked.entries))
  )
}

/** Why the request can't be approved yet, or null. */
export function negativeBlock(
  args: UpdateNegativeKeywordsArgs | null,
  checked: UpdateNegativeKeywordsArgs
): string | null {
  if (args === null) return null
  return changesBlock(
    negativeCounts(negativeRows(args, checked)),
    needsCheck(args, checked),
    "These negative keywords are already in place."
  )
}

export function negativeApproveLabel(args: UpdateNegativeKeywordsArgs): string {
  return applyChangesLabel(negativeCounts(negativeRows(args, args)).apply)
}

// In the order the card names them.
const KIND_NOUNS: Record<NegativeTargetKind, string> = {
  campaign: "campaign",
  ad_group: "ad group",
  list: "list",
  new_list: "new list",
}

/** Names the targets: one by name, or how many of each kind. */
export function targetsText(args: UpdateNegativeKeywordsArgs): string {
  const [first] = args.entries
  if (args.entries.length === 1 && first) return targetName(args, first)
  const parts = (Object.keys(KIND_NOUNS) as NegativeTargetKind[]).flatMap((kind) => {
    const count = args.entries.filter((entry) => entry.kind === kind).length
    if (count === 0) return []
    return [
      kind === "new_list" && count === 1
        ? "a new list"
        : approvalCountLine(count, KIND_NOUNS[kind]),
    ]
  })
  const last = parts.pop()
  return parts.length > 0 ? `${parts.join(", ")} and ${last ?? ""}` : (last ?? "")
}

function searches(count: number): string {
  return `${count.toLocaleString("en-GB")} ${count === 1 ? "search" : "searches"}`
}

export function negativePrompt(args: UpdateNegativeKeywordsArgs): string {
  if (args.entries.length === 0) return "Nothing is left to change."
  const where = accountsText(
    args.accounts,
    args.entries.map((entry) => entry.customerId)
  )
  const add = args.entries.reduce((total, entry) => total + entry.add.length, 0)
  const remove = args.entries.reduce((total, entry) => total + entry.remove.length, 0)
  const targets = targetsText(args)
  if (remove === 0 && add > 0) return `Block ${searches(add)} in ${targets} in ${where}.`
  if (add === 0 && remove > 0) return `Stop blocking ${searches(remove)} in ${targets} in ${where}.`
  if (add + remove === 0) return `Change which campaigns use ${targets} in ${where}.`
  return `Block ${searches(add)} and stop blocking ${searches(remove)} in ${targets} in ${where}.`
}

export function negativeDetails(args: UpdateNegativeKeywordsArgs | null): FanOutDetail[] {
  return args ? [{ label: "Targets", value: String(args.entries.length) }] : []
}

function isRow(value: unknown): value is NegativeRow {
  return (
    isRecord(value) &&
    typeof value["id"] === "string" &&
    typeof value["targetKey"] === "string" &&
    typeof value["name"] === "string"
  )
}

// How the shared cancelled-rows helpers read and restore this card's rows.
export const NEGATIVE_CANCEL_CARD: CancelCard<NegativeEntry, NegativeRow> = {
  isRow,
  parseEntry,
  serializeEntries,
  withRow,
}
