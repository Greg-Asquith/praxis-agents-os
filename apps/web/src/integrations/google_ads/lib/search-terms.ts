// apps/web/src/integrations/google_ads/lib/search-terms.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { ParentRow } from "@/integrations/ads/components/parent-table"
import { collapseSpaces, type KeywordMatchType } from "@/integrations/ads/lib/keyword-notation"
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
import { MATCH_TYPES } from "@/integrations/google_ads/lib/negative-keywords"
import { isRecord } from "@/lib/guards"

export type SearchTermAction = "add_negative" | "add_keyword"
type NegativeLevel = "ad_group" | "campaign" | "list"
type RowState = "change" | "already_set" | "unchecked"

export const ACTION_LABELS: Record<SearchTermAction, string> = {
  add_keyword: "Add Keyword",
  add_negative: "Block",
}

type Reference = { id: string; label: string; value: Record<string, unknown> }

export type SearchTermDecision = {
  action: SearchTermAction
  adGroup: Reference
  campaignId: string
  campaignLabel: string | null
  customerId: string
  // The server's name for the decision, which its check is keyed by.
  key: string
  keywordAdGroup: Reference | null
  level: NegativeLevel | null
  list: Reference | null
  matchType: KeywordMatchType
  term: string
  // The decision as received, so an edit keeps every reference field.
  value: Record<string, unknown>
}

type Figures = {
  clicks: number | null
  conversions: number | null
  cost: number | null
  // What Google says the term already is somewhere in the account, such as a keyword.
  termStatus: string | null
}

const TERM_STATUS_TEXT: Record<string, string> = {
  ADDED: "Already a keyword in this ad group",
  ADDED_EXCLUDED: "Already a keyword, and excluded",
  EXCLUDED: "Already excluded in this ad group",
}

export function termStatusText(status: string | null): string | null {
  return status ? (TERM_STATUS_TEXT[status] ?? null) : null
}

type DecisionCheck =
  | { unavailable: true }
  | (Figures & {
      adGroupName: string | null
      campaignName: string | null
      problem: string | null
      state: Exclude<RowState, "unchecked">
      targetName: string | null
      unavailable: false
    })

export type OptimiseSearchTermsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  checks: Map<string, DecisionCheck>
  decisions: SearchTermDecision[]
  endDate: string
  startDate: string
}

export type SearchTermRow = Figures & {
  action: SearchTermAction
  // The ad group the term matched in, which an edit never changes.
  adGroupKey: string
  adGroupName: string
  campaignName: string
  cancelled: boolean
  customerId: string
  id: string
  matchType: KeywordMatchType
  problem: string | null
  state: RowState
  // The row's target as a `TargetOption` value.
  target: string
  targetName: string
  term: string
  value: Record<string, unknown>
}

const UNAVAILABLE =
  "Google Ads couldn't check this. Check again, or ask the agent to prepare the change again."
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function parseReference(value: unknown, idKey: string, noun: string): Reference | null {
  if (!isRecord(value)) return null
  const id = googleAdsId(value[idKey])
  return id === null ? null : { id, label: textOrNull(value["label"]) ?? `${noun} ${id}`, value }
}

function parseDecision(value: unknown): SearchTermDecision | null {
  if (!isRecord(value)) return null
  const term = textOrNull(value["search_term"])
  const { action, level, match_type: matchType } = value
  const adGroup = parseReference(value["ad_group"], "ad_group_id", "Ad group")
  const raw = isRecord(value["ad_group"]) ? value["ad_group"] : {}
  const customerId = googleAdsId(raw["customer_id"])
  const campaignId = googleAdsId(raw["campaign_id"])
  if (
    term === null ||
    adGroup === null ||
    customerId === null ||
    campaignId === null ||
    (action !== "add_negative" && action !== "add_keyword") ||
    !MATCH_TYPES.includes(matchType as KeywordMatchType) ||
    (level != null && level !== "ad_group" && level !== "campaign" && level !== "list")
  )
    return null
  const collapsed = collapseSpaces(term)
  return {
    action,
    adGroup,
    campaignId,
    campaignLabel: textOrNull(raw["scope_label"]),
    customerId,
    key: `customers/${customerId}/adGroups/${adGroup.id}/${action}/${collapsed.toLowerCase()}`,
    keywordAdGroup: parseReference(value["keyword_ad_group"], "ad_group_id", "Ad group"),
    level: level ?? null,
    list: parseReference(value["negative_list"], "shared_set_id", "List"),
    matchType: matchType as KeywordMatchType,
    term: collapsed,
    value,
  }
}

function parseCheck(value: unknown): DecisionCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const cost = textOrNull(value["cost"])
  return {
    adGroupName: textOrNull(value["ad_group_name"]),
    campaignName: textOrNull(value["campaign_name"]),
    clicks: count(value["clicks"]),
    conversions: count(value["conversions"]),
    cost: cost === null ? null : Number(cost),
    problem: textOrNull(value["problem"]),
    termStatus: textOrNull(value["term_status"]),
    state: value["state"] === "already_set" ? "already_set" : "change",
    targetName: textOrNull(value["target_name"]),
    unavailable: false,
  }
}

/** Reads the request with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseSearchTermsArgs(value: unknown): OptimiseSearchTermsArgs | null {
  if (!isRecord(value) || !Array.isArray(value["decisions"])) return null
  const startDate = textOrNull(value["start_date"])
  const endDate = textOrNull(value["end_date"])
  if (!startDate || !endDate || !DATE_PATTERN.test(startDate) || !DATE_PATTERN.test(endDate))
    return null
  const decisions: SearchTermDecision[] = []
  for (const item of value["decisions"]) {
    const decision = parseDecision(item)
    if (decision === null) return null
    decisions.push(decision)
  }
  const checks = isRecord(value["_checks"]) ? value["_checks"] : {}
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    checks: new Map(Object.entries(checks).map(([key, check]) => [key, parseCheck(check)])),
    decisions,
    endDate,
    startDate,
  }
}

/** Names the criterion a decision adds, so two decisions never add the same one. */
function writeKey(decision: SearchTermDecision): string {
  const target =
    decision.action === "add_keyword"
      ? `keyword:${(decision.keywordAdGroup ?? decision.adGroup).id}`
      : decision.level === "campaign"
        ? `campaign:${decision.campaignId}`
        : decision.level === "list"
          ? `list:${decision.list?.id ?? ""}`
          : `ad_group:${decision.adGroup.id}`
  return `${decision.customerId}|${target}|${decision.matchType}|${decision.term.toLowerCase()}`
}

export type TargetOption = {
  // What the target is, such as "Campaign" or "Negative Keyword List".
  detail: string
  label: string
  // A target found by search carries its reference, since the request doesn't hold it.
  reference?: Record<string, unknown>
  value: string
}

export type TargetSearchKind = "ad_group" | "list"

const LIST_DETAIL = "Negative Keyword List"

/** Where a row's decision can go without searching: for a negative, its ad group, its
 * campaign, or a list in the request; for a keyword, any ad group in the request in the
 * same account. */
export function targetOptions(
  args: OptimiseSearchTermsArgs,
  row: Pick<SearchTermRow, "action" | "adGroupName" | "campaignName" | "customerId" | "value">
): TargetOption[] {
  const decision = parseDecision(row.value)
  if (decision === null) return []
  const same = args.decisions.filter((item) => item.customerId === row.customerId)
  if (row.action === "add_keyword") {
    const groups = new Map<string, string>()
    for (const item of [decision, ...same])
      for (const group of [item.adGroup, item.keywordAdGroup])
        if (group && !groups.has(group.id)) groups.set(group.id, group.label)
    groups.set(decision.adGroup.id, row.adGroupName)
    return [...groups].map(([id, label]) => ({
      detail: id === decision.adGroup.id ? "Ad Group it matched in" : "Ad Group",
      label,
      value: `ad_group:${id}`,
    }))
  }
  return [
    { detail: "Ad Group it matched in", label: row.adGroupName, value: "ad_group" },
    { detail: "Campaign", label: row.campaignName, value: "campaign" },
    ...requestLists(args, row.customerId),
  ]
}

function requestLists(args: OptimiseSearchTermsArgs, customerId: string): TargetOption[] {
  const lists = new Map<string, string>()
  for (const decision of args.decisions)
    if (decision.list && decision.customerId === customerId && !lists.has(decision.list.id))
      lists.set(decision.list.id, decision.list.label)
  return [...lists].map(([id, label]) => ({ detail: LIST_DETAIL, label, value: `list:${id}` }))
}

/** A list or ad group found by search, as a target; null when it's in another account. */
export function searchedTarget(
  kind: TargetSearchKind,
  reference: Record<string, unknown>,
  label: string,
  customerId: string
): TargetOption | null {
  const idKey = kind === "list" ? "shared_set_id" : "ad_group_id"
  const id = googleAdsId(reference[idKey])
  if (id === null || googleAdsId(reference["customer_id"]) !== customerId) return null
  const detail =
    kind === "list"
      ? LIST_DETAIL
      : [textOrNull(reference["scope_label"]), "Ad Group"].filter(Boolean).join(" · ")
  return { detail, label, reference, value: `${kind}:${id}` }
}

/** The targets a selection of negatives can move to together; none when it mixes actions
 * or accounts. */
export function bulkNegativeTargets(
  args: OptimiseSearchTermsArgs,
  rows: readonly Pick<SearchTermRow, "action" | "customerId">[]
): TargetOption[] {
  const customers = new Set(rows.map((row) => row.customerId))
  const [customerId] = customers
  if (customerId === undefined || customers.size > 1) return []
  if (rows.some((row) => row.action !== "add_negative")) return []
  return [
    { detail: "Where each term matched", label: "Its Ad Group", value: "ad_group" },
    { detail: "Of each term's ad group", label: "Its Campaign", value: "campaign" },
    ...requestLists(args, customerId),
  ]
}

function targetValue(decision: SearchTermDecision): string {
  if (decision.action === "add_keyword")
    return `ad_group:${(decision.keywordAdGroup ?? decision.adGroup).id}`
  if (decision.level === "list") return `list:${decision.list?.id ?? ""}`
  return decision.level ?? "ad_group"
}

function figuresFor(
  checks: ReadonlyMap<string, DecisionCheck>,
  decision: SearchTermDecision
): Figures | null {
  // A term's figures don't depend on the action, so an edited row keeps them.
  const base = decision.key.slice(0, decision.key.lastIndexOf(`/${decision.action}/`))
  const term = decision.term.toLowerCase()
  for (const action of ["add_negative", "add_keyword"] as const) {
    const check = checks.get(`${base}/${action}/${term}`)
    if (check && !check.unavailable)
      return {
        clicks: check.clicks,
        conversions: check.conversions,
        cost: check.cost,
        termStatus: check.termStatus,
      }
  }
  return null
}

function decisionRow(
  decision: SearchTermDecision,
  checks: ReadonlyMap<string, DecisionCheck>,
  check: DecisionCheck | undefined,
  cancelled: boolean
): SearchTermRow {
  const seen = check && !check.unavailable ? check : null
  const figures = figuresFor(checks, decision)
  const campaignName = seen?.campaignName ?? decision.campaignLabel ?? "Campaign"
  const adGroupName = seen?.adGroupName ?? decision.adGroup.label
  const fallbackTarget =
    decision.action === "add_keyword"
      ? (decision.keywordAdGroup ?? decision.adGroup).label
      : decision.level === "campaign"
        ? campaignName
        : decision.level === "list"
          ? (decision.list?.label ?? "List")
          : adGroupName
  return {
    action: decision.action,
    adGroupKey: `customers/${decision.customerId}/adGroups/${decision.adGroup.id}`,
    adGroupName,
    campaignName,
    cancelled,
    clicks: figures?.clicks ?? null,
    conversions: figures?.conversions ?? null,
    cost: figures?.cost ?? null,
    customerId: decision.customerId,
    termStatus: figures?.termStatus ?? null,
    id: decision.key,
    matchType: decision.matchType,
    problem:
      cancelled || check === undefined ? null : check.unavailable ? UNAVAILABLE : check.problem,
    state: seen?.state ?? "unchecked",
    target: targetValue(decision),
    targetName: seen?.targetName ?? fallbackTarget,
    term: decision.term,
    value: decision.value,
  }
}

/** Every decision, checked against what Google last answered for, then cancelled ones.
 *
 * Rows are sorted by cost, most first, as the operator works through the costliest terms. */
export function searchTermRows(
  args: OptimiseSearchTermsArgs,
  checked: OptimiseSearchTermsArgs,
  cancelled: readonly Record<string, unknown>[] = []
): SearchTermRow[] {
  const answered = new Map(checked.decisions.map((decision) => [decision.key, decision]))
  const live = args.decisions.map((decision) => {
    const same =
      JSON.stringify(answered.get(decision.key)?.value) === JSON.stringify(decision.value)
    // An edited decision waits for a new check, so its old answer doesn't apply.
    const check = same ? checked.checks.get(decision.key) : undefined
    return decisionRow(decision, checked.checks, check, false)
  })
  const held = new Set(live.map((row) => row.id))
  const gone = cancelled.flatMap((value) => {
    const decision = parseDecision(value)
    return decision && !held.has(decision.key)
      ? [decisionRow(decision, checked.checks, undefined, true)]
      : []
  })
  return [...live, ...gone].sort((a, b) => (b.cost ?? -1) - (a.cost ?? -1))
}

export type SearchTermCounts = {
  alreadySet: number
  apply: number
  blockedCost: number
  cancelled: number
  keywords: number
  negatives: number
  problems: number
  total: number
}

export function searchTermCounts(rows: readonly SearchTermRow[]): SearchTermCounts {
  const live = rows.filter((row) => !row.cancelled)
  // A row with a problem has to be fixed or cancelled, so it doesn't count towards what applies.
  const applies = live.filter((row) => row.problem === null && row.state !== "already_set")
  return {
    alreadySet: live.filter((row) => row.state === "already_set").length,
    apply: applies.length,
    blockedCost: applies
      .filter((row) => row.action === "add_negative")
      .reduce((total, row) => total + (row.cost ?? 0), 0),
    cancelled: rows.length - live.length,
    keywords: applies.filter((row) => row.action === "add_keyword").length,
    negatives: applies.filter((row) => row.action === "add_negative").length,
    problems: live.filter((row) => row.problem !== null).length,
    total: live.length,
  }
}

export type SearchTermEdit = {
  decisions: Record<string, unknown>[]
  // Decisions that left the request, which Undo can restore.
  dropped: Record<string, unknown>[]
}

/** Keeps the first decision for each key and criterion; later ones leave the request. */
function deduplicated(values: readonly Record<string, unknown>[]): SearchTermEdit {
  const keys = new Set<string>()
  const writes = new Set<string>()
  const decisions: Record<string, unknown>[] = []
  const dropped: Record<string, unknown>[] = []
  for (const value of values) {
    const decision = parseDecision(value)
    if (decision === null) continue
    const write = writeKey(decision)
    if (keys.has(decision.key) || writes.has(write)) {
      dropped.push(value)
      continue
    }
    keys.add(decision.key)
    writes.add(write)
    decisions.push(value)
  }
  return { decisions, dropped }
}

function editDecisions(
  args: OptimiseSearchTermsArgs,
  ids: ReadonlySet<string>,
  change: (decision: SearchTermDecision) => Record<string, unknown> | null
): SearchTermEdit {
  const dropped: Record<string, unknown>[] = []
  const next = args.decisions.flatMap((decision) => {
    if (!ids.has(decision.key)) return [decision.value]
    const value = change(decision)
    if (value === null) dropped.push(decision.value)
    return value === null ? [] : [value]
  })
  const edit = deduplicated(next)
  return { decisions: edit.decisions, dropped: [...dropped, ...edit.dropped] }
}

function without(value: Record<string, unknown>, ...keys: string[]): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([key]) => !keys.includes(key)))
}

export function cancelDecisions(args: OptimiseSearchTermsArgs, ids: ReadonlySet<string>) {
  return editDecisions(args, ids, () => null)
}

export function setDecisionAction(
  args: OptimiseSearchTermsArgs,
  ids: ReadonlySet<string>,
  action: SearchTermAction
): SearchTermEdit {
  return editDecisions(args, ids, (decision) => {
    if (decision.action === action) return decision.value
    const base = without(decision.value, "level", "negative_list", "keyword_ad_group")
    // A new negative blocks the term in its campaign, the usual place for it.
    return action === "add_negative" ? { ...base, action, level: "campaign" } : { ...base, action }
  })
}

export function setDecisionMatchType(
  args: OptimiseSearchTermsArgs,
  ids: ReadonlySet<string>,
  matchType: KeywordMatchType
): SearchTermEdit {
  return editDecisions(args, ids, (decision) => ({ ...decision.value, match_type: matchType }))
}

function inAccount(reference: Reference | undefined, customerId: string): reference is Reference {
  return reference !== undefined && googleAdsId(reference.value["customer_id"]) === customerId
}

/** Points each decision at a target option; one it can't take keeps its own. */
export function setDecisionTarget(
  args: OptimiseSearchTermsArgs,
  ids: ReadonlySet<string>,
  target: TargetOption
): SearchTermEdit {
  const [kind, id] = target.value.split(":")
  const lists = new Map(
    args.decisions.flatMap((decision) => (decision.list ? [[decision.list.id, decision.list]] : []))
  )
  const groups = new Map(
    args.decisions.flatMap((decision) =>
      [decision.adGroup, decision.keywordAdGroup].flatMap((group) =>
        group ? [[group.id, group] as const] : []
      )
    )
  )
  if (target.reference && id) {
    const found = { id, label: target.label, value: target.reference }
    if (kind === "list") lists.set(id, found)
    if (kind === "ad_group") groups.set(id, found)
  }
  return editDecisions(args, ids, (decision) => {
    const base = without(decision.value, "level", "negative_list", "keyword_ad_group")
    if (decision.action === "add_keyword") {
      const group = kind === "ad_group" && id ? groups.get(id) : undefined
      if (!inAccount(group, decision.customerId)) return decision.value
      return group.id === decision.adGroup.id ? base : { ...base, keyword_ad_group: group.value }
    }
    if (target.value === "ad_group" || target.value === "campaign")
      return { ...base, level: target.value }
    const list = kind === "list" && id ? lists.get(id) : undefined
    if (!inAccount(list, decision.customerId)) return decision.value
    return { ...base, level: "list", negative_list: list.value }
  })
}

/** Puts cancelled decisions back, unless another decision now adds the same thing. */
export function restoreDecisions(
  args: OptimiseSearchTermsArgs,
  values: readonly Record<string, unknown>[]
): SearchTermEdit {
  return deduplicated([...args.decisions.map((decision) => decision.value), ...values])
}

/** One row per ad group the terms matched in, the costliest first. */
export function searchTermParents(
  rows: readonly SearchTermRow[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>,
  showAccount: boolean
): ParentRow[] {
  const groups = groupedByParent(rows, (row) => row.adGroupKey)
  const spend = (items: readonly SearchTermRow[]) =>
    items.reduce((total, row) => total + (row.cost ?? 0), 0)
  // Sorted on every term's cost, so cancelling an ad group doesn't move its row.
  const sorted = groups.sort((a, b) => spend(b.items) - spend(a.items))
  return sorted.map(({ items, key, live }) => {
    const first = items[0]
    return {
      cancelled: live.length === 0,
      context: showAccount && first ? (accounts.get(first.customerId)?.label ?? null) : null,
      key,
      name: first?.adGroupName ?? key,
      problems: live.filter((row) => row.problem !== null).length,
      values: {
        campaign: first?.campaignName ?? "",
        cost: spend(live),
        terms: live.length,
      },
    }
  })
}

function serializeDecisions(args: OptimiseSearchTermsArgs): Record<string, unknown>[] {
  return args.decisions.map((decision) => decision.value)
}

export function needsCheck(
  args: OptimiseSearchTermsArgs,
  checked: OptimiseSearchTermsArgs
): boolean {
  return (
    [...checked.checks.values()].some((check) => check.unavailable) ||
    JSON.stringify(serializeDecisions(args)) !== JSON.stringify(serializeDecisions(checked))
  )
}

/** Why the request can't be approved yet, or null. */
export function searchTermsBlock(
  args: OptimiseSearchTermsArgs | null,
  checked: OptimiseSearchTermsArgs
): string | null {
  if (args === null) return null
  return changesBlock(
    searchTermCounts(searchTermRows(args, checked)),
    needsCheck(args, checked),
    "These search terms are already in place."
  )
}

export function searchTermsApproveLabel(args: OptimiseSearchTermsArgs): string {
  return applyChangesLabel(searchTermCounts(searchTermRows(args, args)).apply)
}

function day(value: string): string {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  })
}

export function dateRangeText(
  args: Pick<OptimiseSearchTermsArgs, "endDate" | "startDate">
): string {
  return args.startDate === args.endDate
    ? day(args.startDate)
    : `${day(args.startDate)} to ${day(args.endDate)}`
}

export function accountCurrency(args: OptimiseSearchTermsArgs): string | null {
  const [first] = args.decisions
  return first ? (args.accounts.get(first.customerId)?.currencyCode ?? null) : null
}

export function searchTermsPrompt(args: OptimiseSearchTermsArgs): string {
  if (args.decisions.length === 0) return "Nothing is left to change."
  const where = accountsText(
    args.accounts,
    args.decisions.map((decision) => decision.customerId)
  )
  return `Act on ${approvalCountLine(args.decisions.length, "search term")} from ${dateRangeText(args)} in ${where}.`
}

export function searchTermsDetails(args: OptimiseSearchTermsArgs | null): FanOutDetail[] {
  return args
    ? [
        { label: "Search Terms", value: String(args.decisions.length) },
        { label: "Dates", value: dateRangeText(args) },
      ]
    : []
}

/** The card's own record of cancelled decisions, which survives a check's redraw. */
export function parseCancelled(value: unknown): Record<string, unknown>[] {
  if (!isRecord(value) || !Array.isArray(value["decisions"])) return []
  return value["decisions"].filter(isRecord)
}
