// apps/web/src/integrations/meta_ads/lib/ad-set-edits.ts

import type { EditedValue } from "@/components/tool-ui/edited-values"
import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  adScheduleProblem,
  DELIVERY_KINDS,
  deliveryText,
  formatAdSchedule,
  formatAttribution,
  formatFrequencyCap,
  frequencyCapProblem,
  fromText,
  parseAdSchedule,
  parseAttribution,
  parseFrequencyCap,
  type DeliveryKind,
} from "@/integrations/meta_ads/lib/ad-set-delivery"
import { budgetMoney, isBudgetAmount } from "@/integrations/meta_ads/lib/budget-change"
import {
  bidAmountTitle,
  bidLabel,
  isRoas,
  ROAS_FORMAT,
} from "@/integrations/meta_ads/lib/create-ad-set"
import { AMOUNT_FORMAT } from "@/integrations/meta_ads/lib/create-campaign"
import { formatDay } from "@/integrations/meta_ads/lib/create-summary"
import {
  CONVERSION_EVENT_LABELS,
  GOALS,
  STORE_LABELS,
  type Goal,
} from "@/integrations/meta_ads/lib/goals"
import { formatPercentageChange, titleCaseToken } from "@/lib/format"
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
  | "goal"
  | "pixel"
  | "conversion_event"
  | "custom_conversion_id"
  | "page"
  | "app"
  | "app_store"
  | "attribution"
  | "frequency_cap"
  | "ad_schedule"

type SettingKind =
  | "text"
  | "date"
  | "end"
  | "bid"
  | "money"
  | "limit"
  | "ratio"
  | "goal"
  | "asset"
  | "event"
  | "custom"
  | "store"
  | "attribution"
  | "frequency"
  | "schedule"

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
  { key: "goal", title: "Goal", kind: "goal" },
  { key: "pixel", title: "Pixel", kind: "asset" },
  { key: "conversion_event", title: "What Counts as a Result", kind: "event" },
  { key: "custom_conversion_id", title: "What Counts as a Result", kind: "custom" },
  { key: "page", title: "Facebook Page", kind: "asset" },
  { key: "app", title: "App", kind: "asset" },
  { key: "app_store", title: "App Store", kind: "store" },
  { key: "attribution", title: "Attribution Setting", kind: "attribution" },
  { key: "frequency_cap", title: "Frequency Cap", kind: "frequency" },
  { key: "ad_schedule", title: "Ad Scheduling", kind: "schedule" },
]
// The reference ID each asset setting carries, and the entity kind the card picks it from.
export const ASSET_SETTINGS: Partial<Record<SettingKey, { idField: string; entityKind: string }>> =
  {
    pixel: { idField: "pixel_id", entityKind: "meta_ads_pixel" },
    page: { idField: "page_id", entityKind: "meta_ads_page" },
    app: { idField: "application_id", entityKind: "meta_ads_application" },
  }
// Settings the card lays out across both columns.
export const WIDE_KINDS: ReadonlySet<SettingKind> = new Set(["attribution", "schedule"])
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
  // Names of the Pages, pixels, apps, and custom conversions, by ID.
  labels: Record<string, string>
  // Custom conversions the card can offer in place of a standard event.
  conversions: { id: string; name: string }[]
  unavailable: boolean
}

/** One setting's new value, as text the server's checks compare with. */
export type SettingEdit = { key: SettingKey; value: string }
/** One setting's new value as the card edits it: text, a reference, or a structured value. */
export type SettingChange = { key: SettingKey; value: EditedValue }

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
  const settings = SETTINGS.flatMap(({ key }) => {
    const text = settingText(key, value[key])
    return text === null ? [] : [{ key, value: text }]
  })
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

/** A proposed value as text; references by their ID and structured values in one form. */
function settingText(key: SettingKey, value: unknown): string | null {
  const kind = settingKind(key)
  const asset = ASSET_SETTINGS[key]
  if (asset !== undefined) {
    const id = isRecord(value) ? value[asset.idField] : null
    return isNonEmptyString(id) ? id : null
  }
  if (value === "remove" && (kind === "frequency" || kind === "schedule")) return value
  if (isDeliveryKind(kind))
    // A malformed value stays as given, so the card can flag it.
    return value === undefined || value === null
      ? null
      : (deliveryText(kind, value) ?? JSON.stringify(value))
  return typeof value === "string" ? value : null
}

/** The name the card shows for a Page, pixel, app, or custom conversion ID. */
function settingLabel(edit: AdSetEdit, key: SettingKey, id: string): string {
  const reference = edit.raw[key]
  if (
    isRecord(reference) &&
    isNonEmptyString(reference["label"]) &&
    settingText(key, reference) === id
  )
    return reference["label"]
  return edit.check?.labels[id] ?? id
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
    labels: labelValues(value["labels"]),
    conversions: resultLabelList(value["conversions"]),
    unavailable: value["unavailable"] === true,
  }
}

function labelValues(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {}
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === "string")
  )
}

function settingValues(value: unknown): Partial<Record<SettingKey, string | null>> {
  if (!isRecord(value)) return {}
  const values: Partial<Record<SettingKey, string | null>> = {}
  for (const [key, item] of Object.entries(value))
    if (isOneOf(SETTING_KEYS, key) && (item === null || typeof item === "string"))
      values[key] = item === null ? null : serverText(key, item)
  return values
}

/** Puts a structured value the server wrote into the card's form, so the two compare. */
function serverText(key: SettingKey, value: string): string {
  const kind = settingKind(key)
  return isDeliveryKind(kind) ? (deliveryText(kind, fromText(value)) ?? value) : value
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

const EMPTY: Partial<Record<SettingKind, string>> = {
  end: "No end date",
  limit: "No limit",
  attribution: "Meta's default",
  frequency: "No cap",
  schedule: "All day, every day",
}

export function formatSettingValue(
  key: SettingKey,
  value: string | null,
  currency: string | null,
  labels: Record<string, string> = {}
): string {
  const kind = settingKind(key)
  if (value === null || value === "remove" || value === "none") return EMPTY[kind] ?? "Not set"
  const unit = settingUnit(key)
  // A goal outside the card's list shows as Meta's own name, such as Thruplay.
  if (kind === "goal")
    return value in GOALS ? GOALS[value as Goal].label : titleCaseToken(value.toLowerCase(), value)
  if (kind === "event") return CONVERSION_EVENT_LABELS[value] ?? value
  if (kind === "store") return STORE_LABELS[value] ?? value
  if (kind === "asset") return labels[value] ?? value
  if (kind === "custom") return `Custom Conversion: ${labels[value] ?? value}`
  if (isDeliveryKind(kind)) return formatDelivery(kind, value)
  if (kind === "date" || kind === "end") return formatDay(value)
  if (kind === "money") return budgetMoney(value, currency)
  if (kind === "limit") return `${budgetMoney(value, currency)} ${unit ?? ""}`.trim()
  if (kind === "bid") return bidLabel(value)
  if (kind === "ratio") return `${value} ${unit ?? ""}`.trim()
  return value
}

function isDeliveryKind(kind: SettingKind): kind is DeliveryKind {
  return DELIVERY_KINDS.has(kind)
}

function formatDelivery(kind: DeliveryKind, text: string): string {
  const value = fromText(text)
  if (kind === "attribution") {
    const attribution = parseAttribution(value)
    return attribution ? formatAttribution(attribution) : "Not set"
  }
  if (kind === "frequency") {
    const cap = parseFrequencyCap(value)
    return cap ? formatFrequencyCap(cap) : "Not set"
  }
  const schedule = parseAdSchedule(value)
  return schedule ? formatAdSchedule(schedule) : "Not set"
}

/** Names for every Page, pixel, app, and custom conversion this ad set's card shows. */
export function adSetLabels(edit: AdSetEdit): Record<string, string> {
  const labels = { ...edit.check?.labels }
  for (const conversion of edit.check?.conversions ?? []) labels[conversion.id] = conversion.name
  for (const setting of edit.settings)
    if (ASSET_SETTINGS[setting.key] !== undefined)
      labels[setting.value] = settingLabel(edit, setting.key, setting.value)
  return labels
}

/** The new values on one line, for the ad set's closed row. */
export function adSetSummary(edit: AdSetEdit, strategy: string | null): string {
  const currency = edit.check?.currency ?? null
  const labels = adSetLabels(edit)
  return edit.settings
    .map(
      (setting) =>
        `${settingTitle(setting.key, strategy)}: ${formatSettingValue(setting.key, setting.value, currency, labels)}`
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
  if (kind === "custom" && !/^[0-9]+$/.test(value)) return "Enter the custom conversion's ID."
  if (kind === "frequency" && value !== "remove") return frequencyCapProblem(fromText(value))
  if (kind === "schedule" && value !== "remove") return adScheduleProblem(fromText(value))
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
  change: { included: boolean } | SettingChange
): Record<string, unknown>[] {
  return rows.flatMap((row) => {
    const same = row.edit.id === id
    const included = same && "included" in change ? change.included : row.included
    if (!included) return []
    if (!same || !("key" in change)) return [row.edit.raw]
    // One "What Counts as a Result" choice: an event or a custom conversion, never both.
    const other = RESULT_PAIR[change.key]
    const kept = Object.entries(row.edit.raw).filter(([key]) => key !== other)
    return [{ ...Object.fromEntries(kept), [change.key]: change.value }]
  })
}

const RESULT_PAIR: Partial<Record<SettingKey, SettingKey>> = {
  conversion_event: "custom_conversion_id",
  custom_conversion_id: "conversion_event",
}

/** The value now for a setting; for what counts as a result, whichever of the two is set. */
export function currentSetting(edit: AdSetEdit, key: SettingKey): SettingEdit {
  const before = edit.check?.before ?? {}
  const other = RESULT_PAIR[key]
  if (other !== undefined && !before[key] && before[other])
    return { key: other, value: before[other] }
  return { key, value: before[key] ?? "" }
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
  labels: Record<string, string>
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
    labels: resultLabels(value["labels"]),
    outcome: value["outcome"],
    errorCode: text("error_code"),
    message: text("message"),
  }
}

function resultLabels(value: unknown): Record<string, string> {
  return Object.fromEntries(resultLabelList(value).map((item) => [item.id, item.name]))
}

/** IDs with names, as the server lists them. */
function resultLabelList(value: unknown): { id: string; name: string }[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) =>
    isRecord(item) && isNonEmptyString(item["id"]) && typeof item["name"] === "string"
      ? [{ id: item["id"], name: item["name"] }]
      : []
  )
}
