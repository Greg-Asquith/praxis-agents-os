// apps/web/src/integrations/meta_ads/lib/ad-set-edits.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { budgetMoney, isBudgetAmount } from "@/integrations/meta_ads/lib/budget-change"
import {
  bidAmountTitle,
  bidLabel,
  isRoas,
  ROAS_FORMAT,
} from "@/integrations/meta_ads/lib/create-ad-set"
import { AMOUNT_FORMAT } from "@/integrations/meta_ads/lib/create-campaign"
import { formatDay } from "@/integrations/meta_ads/lib/create-summary"
import { formatPercentageChange } from "@/lib/format"
import { isDateString, isNonEmptyString, isOneOf, isRecord, isStringArray } from "@/lib/guards"

export type SettingKey =
  | "name"
  | "start_date"
  | "end_date"
  | "bid_strategy"
  | "bid_amount"
  | "min_roas"
  | "min_daily_spend"
  | "max_daily_spend"
  | "min_lifetime_spend"
  | "max_lifetime_spend"
  | "eu_payer"
  | "eu_beneficiary"

type SettingKind = "text" | "date" | "end" | "bid" | "money" | "limit" | "ratio"

// In the order the card and the tool list them; titles and units match the create cards.
const SETTINGS: readonly { key: SettingKey; title: string; kind: SettingKind; unit?: string }[] = [
  { key: "name", title: "Name", kind: "text" },
  { key: "start_date", title: "Start Date", kind: "date" },
  { key: "end_date", title: "End Date", kind: "end" },
  { key: "bid_strategy", title: "Bid Strategy", kind: "bid" },
  { key: "bid_amount", title: "Bid Amount", kind: "money" },
  { key: "min_roas", title: "Minimum Return on Ad Spend", kind: "ratio", unit: "times spend" },
  { key: "min_daily_spend", title: "Daily Spend at Least", kind: "limit", unit: "a day" },
  { key: "max_daily_spend", title: "Daily Spend at Most", kind: "limit", unit: "a day" },
  { key: "min_lifetime_spend", title: "Lifetime Spend at Least", kind: "limit", unit: "in total" },
  { key: "max_lifetime_spend", title: "Lifetime Spend at Most", kind: "limit", unit: "in total" },
  { key: "eu_payer", title: "Who Pays for the Ads", kind: "text" },
  { key: "eu_beneficiary", title: "Who the Ads Benefit", kind: "text" },
]
const SETTING_KEYS: ReadonlySet<SettingKey> = new Set(SETTINGS.map((setting) => setting.key))
const KINDS = new Map(SETTINGS.map((setting) => [setting.key, setting]))

type AdSetCheck = {
  currency: string | null
  // Each setting now; null means not set.
  before: Partial<Record<SettingKey, string | null>>
  // The values the problems were found for.
  requested: Partial<Record<SettingKey, string | null>>
  problems: string[]
  // Effects that can cost results for a while.
  warnings: string[]
  notes: string[]
  unavailable: boolean
}

export type SettingEdit = { key: SettingKey; value: string }

export type AdSetEdit = {
  id: string
  accountId: string
  name: string
  scope: string | null
  settings: SettingEdit[]
  check: AdSetCheck | null
  // The entry as sent, so edits keep the reference the card doesn't change.
  raw: Record<string, unknown>
}

export type AdSetEditArgs = { edits: AdSetEdit[] }

/** One proposed ad set, kept when the operator drops it so it can come back. */
export type AdSetEditRow = { edit: AdSetEdit; included: boolean }

/** The setting's name; a bid amount takes its name from the strategy, when known. */
export function settingTitle(key: SettingKey, strategy: string | null = null): string {
  if (key === "bid_amount" && (strategy === "bid_cap" || strategy === "cost_per_result_goal"))
    return bidAmountTitle(strategy)
  return KINDS.get(key)?.title ?? key
}

/** The unit shown after an amount, such as "a day". */
export function settingUnit(key: SettingKey): string | undefined {
  return KINDS.get(key)?.unit
}

/** The bid strategy the ad set has once this edit applies. */
export function editStrategy(edit: AdSetEdit): string | null {
  const requested = edit.settings.find((setting) => setting.key === "bid_strategy")
  return requested?.value ?? edit.check?.before.bid_strategy ?? null
}

export function settingKind(key: SettingKey): SettingKind {
  return KINDS.get(key)?.kind ?? "text"
}

export function parseAdSetEditArgs(value: unknown): AdSetEditArgs | null {
  if (!isRecord(value) || !Array.isArray(value["changes"])) return null
  const checks = isRecord(value["_checks"]) ? value["_checks"] : {}
  const edits: AdSetEdit[] = []
  for (const item of value["changes"]) {
    const edit = parseEdit(item, checks)
    if (edit === null) return null
    edits.push(edit)
  }
  return { edits }
}

function parseEdit(value: unknown, checks: Record<string, unknown>): AdSetEdit | null {
  if (!isRecord(value) || !isRecord(value["ad_set"])) return null
  const reference = value["ad_set"]
  const id = reference["adset_id"]
  if (!isNonEmptyString(id)) return null
  const settings = SETTINGS.flatMap(({ key }) =>
    typeof value[key] === "string" ? [{ key, value: value[key] }] : []
  )
  return {
    id,
    accountId: typeof reference["account_id"] === "string" ? reference["account_id"] : "",
    name: isNonEmptyString(reference["label"]) ? reference["label"] : id,
    scope: isNonEmptyString(reference["scope_label"]) ? reference["scope_label"] : null,
    settings,
    check: parseCheck(checks[id]),
    raw: value,
  }
}

function parseCheck(value: unknown): AdSetCheck | null {
  if (!isRecord(value)) return null
  return {
    currency: isNonEmptyString(value["currency"]) ? value["currency"] : null,
    before: settingValues(value["before"]),
    requested: settingValues(value["requested"]),
    problems: isStringArray(value["problems"]) ? value["problems"] : [],
    warnings: isStringArray(value["warnings"]) ? value["warnings"] : [],
    notes: isStringArray(value["notes"]) ? value["notes"] : [],
    unavailable: value["unavailable"] === true,
  }
}

function settingValues(value: unknown): Partial<Record<SettingKey, string | null>> {
  if (!isRecord(value)) return {}
  const values: Partial<Record<SettingKey, string | null>> = {}
  for (const [key, item] of Object.entries(value))
    if (isOneOf(SETTING_KEYS, key) && (item === null || typeof item === "string"))
      values[key] = item
  return values
}

/** The value as the tool compares it: removing a limit or end date means not set. */
function requestedValue(value: string): string | null {
  return value === "remove" || value === "none" ? null : value
}

/** True when the server's problems were found for exactly the values now on the card. */
function checkIsCurrent(edit: AdSetEdit): boolean {
  const check = edit.check
  if (check === null) return false
  const requested = Object.keys(check.requested)
  return (
    requested.length === edit.settings.length &&
    edit.settings.every(
      (setting) =>
        setting.key in check.requested &&
        check.requested[setting.key] === requestedValue(setting.value)
    )
  )
}

export function currentProblems(edit: AdSetEdit): string[] {
  return checkIsCurrent(edit) ? (edit.check?.problems ?? []) : []
}

export function adSetWarnings(edit: AdSetEdit): string[] {
  return checkIsCurrent(edit) ? (edit.check?.warnings ?? []) : []
}

/** Notes under an ad set; a note on values since edited could be wrong, so it says so. */
export function adSetNotes(edit: AdSetEdit): string[] {
  const check = edit.check
  if (check === null || check.unavailable)
    return ["This ad set couldn't be checked before approval. Meta checks it when you approve."]
  if (!checkIsCurrent(edit))
    return ["You changed these values, so Meta checks them again when you approve."]
  return check.notes
}

export function formatSettingValue(
  key: SettingKey,
  value: string | null,
  currency: string | null
): string {
  const kind = settingKind(key)
  if (value === null || value === "remove" || value === "none")
    return kind === "end" ? "No end date" : kind === "limit" ? "No limit" : "Not set"
  const unit = settingUnit(key)
  if (kind === "date" || kind === "end") return formatDay(value)
  if (kind === "money") return budgetMoney(value, currency)
  if (kind === "limit") return `${budgetMoney(value, currency)} ${unit ?? ""}`.trim()
  if (kind === "bid") return bidLabel(value)
  if (kind === "ratio") return `${value} ${unit ?? ""}`.trim()
  return value
}

/** The new values on one line, for the ad set's closed row. */
export function adSetSummary(edit: AdSetEdit, strategy: string | null): string {
  const currency = edit.check?.currency ?? null
  return edit.settings
    .map(
      (setting) =>
        `${settingTitle(setting.key, strategy)}: ${formatSettingValue(setting.key, setting.value, currency)}`
    )
    .join(" · ")
}

/** How far an amount moves from its current value, such as "-20%", or null. */
export function settingChange(setting: SettingEdit, before: string | null): string | null {
  const kind = settingKind(setting.key)
  if (before === null || !(kind === "money" || kind === "limit" || kind === "ratio")) return null
  const change = formatPercentageChange(Number(before), Number(setting.value))
  return change === "—" || setting.value.trim() === "" ? null : change
}

/** Why one value on the card can't be sent, or null. */
export function settingProblem(setting: SettingEdit): string | null {
  const kind = settingKind(setting.key)
  const value = setting.value.trim()
  if (kind === "text" && value === "") return "Enter some text."
  if ((kind === "money" || kind === "limit") && !(kind === "limit" && value === "remove"))
    return isBudgetAmount(value) ? null : AMOUNT_FORMAT
  if (kind === "date" || (kind === "end" && value !== "none"))
    return isDateString(value) ? null : "Choose a date."
  if (kind === "ratio" && !isRoas(value)) return ROAS_FORMAT
  return null
}

/** Why the proposed changes can't be approved yet, or null. */
export function adSetEditProblem(args: AdSetEditArgs | null): string | null {
  if (args === null) return null
  if (args.edits.length === 0) return "Keep at least one ad set, or decline this request."
  if (args.edits.some((edit) => edit.settings.some((setting) => settingProblem(setting))))
    return "Correct the highlighted values before approving."
  if (args.edits.some((edit) => currentProblems(edit).length > 0))
    return "Change the ad sets Meta won't accept or switch them off, or decline this request."
  return null
}

/** The proposed ad sets with the ones the operator dropped, in the proposed order. */
export function adSetEditRows(proposed: AdSetEditArgs, current: AdSetEditArgs): AdSetEditRow[] {
  const kept = new Map(current.edits.map((edit) => [edit.id, edit]))
  return proposed.edits.map((edit) => {
    const edited = kept.get(edit.id)
    return { edit: edited ?? edit, included: edited !== undefined }
  })
}

/** The `changes` argument after setting one value, or including or dropping an ad set. */
export function editAdSets(
  rows: readonly AdSetEditRow[],
  id: string,
  change: { included: boolean } | SettingEdit
): Record<string, unknown>[] {
  return rows.flatMap((row) => {
    const same = row.edit.id === id
    const included = same && "included" in change ? change.included : row.included
    if (!included) return []
    return [
      same && "key" in change ? { ...row.edit.raw, [change.key]: change.value } : row.edit.raw,
    ]
  })
}

export function adSetEditDetails(args: AdSetEditArgs | null): FanOutDetail[] {
  if (args === null) return []
  return [{ label: "Ad sets", value: String(args.edits.length) }]
}

// Result models

type EditOutcomeToken = "updated" | "already_set" | "failed" | "unverified"
const OUTCOMES: ReadonlySet<EditOutcomeToken> = new Set([
  "updated",
  "already_set",
  "failed",
  "unverified",
])

type SettingResult = {
  key: SettingKey
  before: string | null
  requested: string | null
  after: string | null
}

type AdSetEditOutcome = {
  id: string
  name: string
  changes: SettingResult[]
  outcome: EditOutcomeToken
  errorCode: string | null
  message: string | null
}

export type AdSetEditResult = { accountId: string; currency: string; adSets: AdSetEditOutcome[] }

export function parseAdSetEditResult(value: unknown): AdSetEditResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["account_id"]) ||
    !isNonEmptyString(value["currency"]) ||
    !Array.isArray(value["ad_sets"])
  )
    return null
  const adSets: AdSetEditOutcome[] = []
  for (const item of value["ad_sets"]) {
    const row = parseOutcome(item)
    if (row === null) return null
    adSets.push(row)
  }
  return { accountId: value["account_id"], currency: value["currency"], adSets }
}

function parseOutcome(value: unknown): AdSetEditOutcome | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["adset_id"]) ||
    !isOneOf(OUTCOMES, value["outcome"]) ||
    !Array.isArray(value["changes"])
  )
    return null
  const changes: SettingResult[] = []
  for (const item of value["changes"]) {
    if (!isRecord(item) || !isOneOf(SETTING_KEYS, item["setting"])) return null
    const text = (key: string) => (typeof item[key] === "string" ? item[key] : null)
    changes.push({
      key: item["setting"],
      before: text("before"),
      requested: text("requested"),
      after: text("after"),
    })
  }
  const text = (key: string) => (typeof value[key] === "string" ? value[key] : null)
  return {
    id: value["adset_id"],
    name: isNonEmptyString(value["name"]) ? value["name"] : value["adset_id"],
    changes,
    outcome: value["outcome"],
    errorCode: text("error_code"),
    message: text("message"),
  }
}
