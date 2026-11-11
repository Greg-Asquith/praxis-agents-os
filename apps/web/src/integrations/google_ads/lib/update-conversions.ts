// apps/web/src/integrations/google_ads/lib/update-conversions.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  accountsText,
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import {
  applyChangesLabel,
  approvalCountLine,
  changesBlock,
  unavailableProblem,
} from "@/integrations/google_ads/lib/copy"
import { googleAdsId, textOrNull } from "@/integrations/google_ads/lib/field-values"
import {
  editedSettingChanges,
  parseSettingMap,
  restoredSettingChanges,
  settingsNeedCheck,
  soleRow,
  withoutKey,
} from "@/integrations/google_ads/lib/setting-changes"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import { formatCurrencyAmount } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const ACTION_SETTINGS = [
  "status",
  "primary",
  "default_value",
  "currency",
  "always_use_default_value",
  "counting",
  "click_through_days",
  "view_through_days",
] as const

export const CONVERSION_SETTINGS = [...ACTION_SETTINGS, "biddable"] as const

export type ConversionSetting = (typeof CONVERSION_SETTINGS)[number]
// Card terms, as the server sends them: the value as a decimal string, windows in days.
export type ConversionValue = string | number | boolean | null

export const STATUSES = ["ENABLED", "HIDDEN"] as const
export const COUNTINGS = ["ONE_PER_CLICK", "MANY_PER_CLICK"] as const

export const CONVERSION_SETTING_TITLES: Record<ConversionSetting, string> = {
  always_use_default_value: "Always Use Default Value",
  biddable: "Counts Towards Account Goals",
  click_through_days: "Click-Through Window",
  counting: "Counting",
  currency: "Value Currency",
  default_value: "Default Value",
  primary: "Goal Type",
  status: "Status",
  view_through_days: "View-Through Window",
}

export const STATUS_LABELS: Record<(typeof STATUSES)[number], string> = {
  ENABLED: "Enabled",
  HIDDEN: "Hidden",
}

export const HIDDEN_NOTE = "Hidden. Stops recording conversions."

export const COUNTING_LABELS: Record<(typeof COUNTINGS)[number], string> = {
  MANY_PER_CLICK: "Every",
  ONE_PER_CLICK: "One per click",
}

// Each window's range in days, as Google allows it.
const WINDOW_DAYS: Record<"click_through_days" | "view_through_days", [number, number]> = {
  click_through_days: [1, 90],
  view_through_days: [1, 30],
}

// Changes to these alter what Smart Bidding optimises for.
const BIDDING_SETTINGS = new Set<ConversionSetting>([
  "status",
  "primary",
  "default_value",
  "currency",
  "always_use_default_value",
  "biddable",
])

type ConversionItem = {
  customerId: string
  // The entry as received, so an edit keeps every reference field.
  entry: Record<string, unknown>
  key: string
  kind: "action" | "goal"
  label: string
  requested: Partial<Record<ConversionSetting, ConversionValue>>
}

type ConversionCheck =
  | { unavailable: true }
  | {
      unavailable: false
      // Over the last 30 days, primary or not; null when Google's report couldn't be read.
      conversions: number | null
      current: Partial<Record<ConversionSetting, ConversionValue>>
      name: string | null
      problem: string | null
      requested: Partial<Record<ConversionSetting, ConversionValue>>
    }

export type UpdateConversionsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  checks: Map<string, ConversionCheck>
  items: ConversionItem[]
}

// A setting the operator cancelled, kept beside the request so Undo can bring it back.
export type CancelledConversionSetting = {
  key: string
  kind: "action" | "goal"
  // The row's name when it was cancelled.
  label: string
  // The `conversion_action` or `goal` reference.
  reference: Record<string, unknown>
  setting: ConversionSetting
  value: ConversionValue
}

export type ConversionRow = {
  cancelled: boolean
  conversions: number | null
  customerId: string
  id: string
  item: ConversionItem | null
  key: string
  kind: "action" | "goal"
  name: string
  // Blocks approval while set.
  problem: string | null
  setting: ConversionSetting
  // Same as the live value, so nothing is sent for it.
  unchanged: boolean
  value: ConversionValue
  // Undefined when the live value couldn't be read.
  was: ConversionValue | undefined
}

export type ConversionCounts = {
  actions: number
  apply: number
  goals: number
  problems: number
  total: number
}

const UNAVAILABLE_PROBLEM = unavailableProblem("conversion")

function windowDays(setting: "click_through_days" | "view_through_days", value: unknown) {
  const [low, high] = WINDOW_DAYS[setting]
  return typeof value === "number" && Number.isInteger(value) && value >= low && value <= high
    ? value
    : undefined
}

/** Reads a value Google holds by its type alone, since it can be one no request may ask for. */
export function liveConversionValue(
  setting: ConversionSetting,
  value: unknown
): ConversionValue | undefined {
  if (value === null) return null
  switch (setting) {
    case "primary":
    case "always_use_default_value":
    case "biddable":
      return typeof value === "boolean" ? value : undefined
    case "click_through_days":
    case "view_through_days":
      return typeof value === "number" && Number.isInteger(value) ? value : undefined
    case "status":
    case "counting":
    case "default_value":
    case "currency":
      return typeof value === "string" && value !== "" ? value : undefined
  }
}

/** Reads one setting's requested value in card terms; undefined when a request can't ask for it. */
export function conversionValue(
  setting: ConversionSetting,
  value: unknown
): ConversionValue | undefined {
  if (value === null) return null
  switch (setting) {
    case "status":
      return STATUSES.find((item) => item === value)
    case "counting":
      return COUNTINGS.find((item) => item === value)
    case "primary":
    case "always_use_default_value":
    case "biddable":
      return typeof value === "boolean" ? value : undefined
    case "default_value":
      return typeof value === "string" && /^\d{1,12}(\.\d{1,6})?$/.test(value)
        ? String(Number(value))
        : undefined
    case "currency":
      return typeof value === "string" && /^[A-Z]{3}$/.test(value) ? value : undefined
    case "click_through_days":
    case "view_through_days":
      return windowDays(setting, value)
  }
}

function requestedOf(
  kind: "action" | "goal",
  entry: Record<string, unknown>
): Partial<Record<ConversionSetting, ConversionValue>> {
  const values: Partial<Record<ConversionSetting, ConversionValue>> = {}
  for (const setting of kind === "goal" ? (["biddable"] as const) : ACTION_SETTINGS) {
    const value = conversionValue(setting, entry[setting])
    if (value !== undefined && value !== null) values[setting] = value
  }
  return values
}

function parseItem(kind: "action" | "goal", value: unknown): ConversionItem | null {
  const field = kind === "goal" ? "goal" : "conversion_action"
  if (!isRecord(value) || !isRecord(value[field])) return null
  const reference = value[field]
  const customerId = googleAdsId(reference["customer_id"])
  if (customerId === null) return null
  let key: string
  let label: string
  if (kind === "action") {
    const id = googleAdsId(reference["conversion_action_id"])
    if (id === null) return null
    key = `customers/${customerId}/conversionActions/${id}`
    label = textOrNull(reference["label"]) ?? key
  } else {
    const category = textOrNull(reference["category"])
    const origin = textOrNull(reference["origin"])
    if (category === null || origin === null) return null
    key = `customers/${customerId}/customerConversionGoals/${category}~${origin}`
    // The reference's label is the agent's wording, so the goal is named from what it targets.
    label = `${googleAdsTokenLabel(category)} · ${googleAdsTokenLabel(origin)}`
  }
  return { customerId, entry: value, key, kind, label, requested: requestedOf(kind, value) }
}

function parseCheck(value: unknown): ConversionCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const conversions = value["conversions"]
  return {
    unavailable: false,
    conversions:
      typeof conversions === "number" && Number.isFinite(conversions) ? conversions : null,
    current: parseSettingMap(CONVERSION_SETTINGS, liveConversionValue, value["current"]),
    name: textOrNull(value["name"]),
    problem: textOrNull(value["problem"]),
    requested: parseSettingMap(CONVERSION_SETTINGS, conversionValue, value["requested"]),
  }
}

/** Reads `changes` and `account_goals` with the trusted `_accounts` and `_checks` beside them. */
export function parseUpdateConversionsArgs(value: unknown): UpdateConversionsArgs | null {
  if (!isRecord(value)) return null
  const items: ConversionItem[] = []
  for (const [field, kind] of [
    ["changes", "action"],
    ["account_goals", "goal"],
  ] as const) {
    const raw = value[field] ?? []
    if (!Array.isArray(raw)) return null
    for (const entry of raw) {
      const item = parseItem(kind, entry)
      if (item === null || items.some((other) => other.key === item.key)) return null
      items.push(item)
    }
  }
  const rawChecks = isRecord(value["_checks"]) ? value["_checks"] : {}
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    checks: new Map(Object.entries(rawChecks).map(([key, check]) => [key, parseCheck(check)])),
    items,
  }
}

function rowOf(
  item: ConversionItem | null,
  cancelled: CancelledConversionSetting | null,
  setting: ConversionSetting,
  value: ConversionValue,
  check: ConversionCheck | undefined
): ConversionRow {
  const key = item?.key ?? cancelled?.key ?? ""
  const live = check && !check.unavailable ? check : null
  const was = live ? (live.current[setting] ?? null) : undefined
  // Google answered for the value it was checked with, so an edited value waits for a new check.
  const checked = live !== null && live.requested[setting] === value
  const reference = cancelled?.reference ?? {}
  return {
    cancelled: item === null,
    conversions: live?.conversions ?? null,
    customerId: item?.customerId ?? googleAdsId(reference["customer_id"]) ?? "",
    id: `${key}|${setting}`,
    item,
    key,
    kind: item?.kind ?? cancelled?.kind ?? "action",
    name: live?.name ?? item?.label ?? cancelled?.label ?? key,
    problem: live === null ? UNAVAILABLE_PROBLEM : checked ? live.problem : null,
    setting,
    unchanged: was !== undefined && was === value,
    value,
    was,
  }
}

/** One row per item and setting, with cancelled settings after the ones still requested. */
export function conversionRows(
  args: UpdateConversionsArgs,
  checked: UpdateConversionsArgs,
  cancelled: readonly CancelledConversionSetting[] = []
): ConversionRow[] {
  const rows: ConversionRow[] = []
  for (const item of args.items)
    for (const setting of CONVERSION_SETTINGS) {
      const value = item.requested[setting]
      if (value !== undefined)
        rows.push(rowOf(item, null, setting, value, checked.checks.get(item.key)))
    }
  const live = new Set(rows.map((row) => row.id))
  for (const item of cancelled)
    if (!live.has(`${item.key}|${item.setting}`))
      rows.push(rowOf(null, item, item.setting, item.value, checked.checks.get(item.key)))
  return rows
}

export function conversionCounts(rows: readonly ConversionRow[]): ConversionCounts {
  const live = rows.filter((row) => !row.cancelled)
  const keys = (kind: "action" | "goal") =>
    new Set(live.filter((row) => row.kind === kind).map((row) => row.key)).size
  return {
    actions: keys("action"),
    apply: live.filter((row) => !row.unchanged).length,
    goals: keys("goal"),
    problems: live.filter((row) => row.problem !== null).length,
    total: live.length,
  }
}

/** Whether any change sent alters what bidding optimises for. */
export function changesBidding(rows: readonly ConversionRow[]): boolean {
  return rows.some((row) => !row.cancelled && !row.unchanged && BIDDING_SETTINGS.has(row.setting))
}

type Kind = ConversionItem["kind"]
type Entry = Record<string, unknown>
type EditedFields = { account_goals: Entry[]; changes: Entry[] }

const settingCard = (kind: Kind) => ({
  requestedOf: (entry: Entry) => requestedOf(kind, entry),
  settings: CONVERSION_SETTINGS,
  withSetting: (entry: Entry, setting: ConversionSetting, value: ConversionValue | undefined) =>
    value === undefined ? withoutKey(entry, setting) : { ...entry, [setting]: value },
})

/** Builds both request fields, each from the items of its own kind. */
function bothFields(
  args: UpdateConversionsArgs,
  entries: (items: ConversionItem[], kind: Kind) => Entry[]
): EditedFields {
  const of = (kind: Kind) =>
    entries(
      args.items.filter((item) => item.kind === kind),
      kind
    )
  return { account_goals: of("goal"), changes: of("action") }
}

/** Both request fields with one setting set on the given rows, or cancelled when undefined. */
export function editedConversions(
  args: UpdateConversionsArgs,
  ids: ReadonlySet<string>,
  value: (row: { key: string; setting: ConversionSetting }) => ConversionValue | undefined
): EditedFields {
  return bothFields(args, (items, kind) =>
    editedSettingChanges(settingCard(kind), items, ids, value)
  )
}

/** Puts cancelled settings back, adding their entry again when it had left the request. */
export function restoredConversions(
  args: UpdateConversionsArgs,
  cancelled: readonly CancelledConversionSetting[]
): EditedFields {
  return bothFields(args, (items, kind) =>
    restoredSettingChanges(
      settingCard(kind),
      items,
      cancelled.filter((item) => item.kind === kind),
      (item) => ({ [kind === "goal" ? "goal" : "conversion_action"]: item.reference })
    )
  )
}

/** Settings the request doesn't change on an action yet, each starting at its live value. */
export function addableConversionSettings(
  checked: UpdateConversionsArgs,
  rows: readonly ConversionRow[],
  key: string
): { setting: ConversionSetting; value: ConversionValue }[] {
  const check = checked.checks.get(key)
  if (!check || check.unavailable || key.includes("/customerConversionGoals/")) return []
  const present = new Set(rows.filter((row) => row.key === key).map((row) => row.setting))
  return ACTION_SETTINGS.flatMap((setting) => {
    // A setting Google left unset, or holds a value no request can ask for, has no start.
    const value = conversionValue(setting, check.current[setting])
    return present.has(setting) || value === undefined || value === null ? [] : [{ setting, value }]
  })
}

/** Both request fields with a setting added to one action already in the request. */
export function addedConversionSetting(
  args: UpdateConversionsArgs,
  key: string,
  setting: ConversionSetting,
  value: ConversionValue
): EditedFields {
  return bothFields(args, (items) =>
    items.map((item) => (item.key === key ? { ...item.entry, [setting]: value } : item.entry))
  )
}

export function parseCancelledConversionSettings(value: unknown): CancelledConversionSetting[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (
      !isRecord(item) ||
      !isRecord(item["reference"]) ||
      typeof item["key"] !== "string" ||
      typeof item["label"] !== "string" ||
      (item["kind"] !== "action" && item["kind"] !== "goal")
    )
      return []
    const setting = CONVERSION_SETTINGS.find((name) => name === item["setting"])
    const parsed = setting ? conversionValue(setting, item["value"]) : undefined
    return setting && parsed !== undefined
      ? [
          {
            key: item["key"],
            kind: item["kind"],
            label: item["label"],
            reference: item["reference"],
            setting,
            value: parsed,
          },
        ]
      : []
  })
}

export function conversionsNeedCheck(args: UpdateConversionsArgs, checked: UpdateConversionsArgs) {
  return settingsNeedCheck(
    CONVERSION_SETTINGS,
    { changes: args.items, checks: args.checks },
    { changes: checked.items, checks: checked.checks }
  )
}

/** Why the request can't be approved yet, or null. */
export function conversionsBlock(
  args: UpdateConversionsArgs | null,
  checked: UpdateConversionsArgs
): string | null {
  if (args === null) return null
  return changesBlock(
    conversionCounts(conversionRows(args, checked)),
    conversionsNeedCheck(args, checked),
    "These conversions already have these settings."
  )
}

/** A setting's value in the words the card uses. */
export function conversionValueText(
  setting: ConversionSetting,
  value: ConversionValue | undefined,
  currency: string | null
): string {
  if (value === undefined) return "—"
  if (value === null) return "None"
  if (setting === "primary") return value === true ? "Primary" : "Secondary"
  if (typeof value === "boolean") return value ? "Yes" : "No"
  if (typeof value === "number") return value === 1 ? "1 day" : `${String(value)} days`
  const status = STATUSES.find((item) => item === value)
  if (setting === "status") return status ? STATUS_LABELS[status] : googleAdsTokenLabel(value)
  const counting = COUNTINGS.find((item) => item === value)
  if (setting === "counting")
    return counting ? COUNTING_LABELS[counting] : googleAdsTokenLabel(value)
  if (setting === "default_value" && currency) return formatCurrencyAmount(value, currency)
  return value
}

/** The currency a row's value is in: the one the request sets, the action's, or the account's. */
export function conversionCurrency(args: UpdateConversionsArgs, row: ConversionRow): string | null {
  const requested = row.item?.requested.currency
  const check = args.checks.get(row.key)
  const live = check && !check.unavailable ? check.current.currency : null
  return (
    (typeof requested === "string" ? requested : null) ??
    (typeof live === "string" ? live : null) ??
    args.accounts.get(row.customerId)?.currencyCode ??
    null
  )
}

export function conversionsPrompt(args: UpdateConversionsArgs): string {
  const rows = conversionRows(args, args)
  if (rows.length === 0) return "Nothing is left to change."
  const sole = soleRow(rows)
  if (sole) {
    if (sole.setting === "primary")
      return `Make ${sole.name} a ${sole.value === true ? "primary" : "secondary"} conversion.`
    if (sole.setting === "biddable")
      return sole.value === true
        ? `Count ${sole.name} towards account goals.`
        : `Stop counting ${sole.name} towards account goals.`
    return `Change the ${CONVERSION_SETTING_TITLES[sole.setting].toLowerCase()} of ${sole.name}.`
  }
  const where = accountsText(
    args.accounts,
    args.items.map((item) => item.customerId)
  )
  return `Change ${approvalCountLine(rows.length, "conversion setting")} in ${where}.`
}

export function conversionsApproveLabel(args: UpdateConversionsArgs): string {
  return applyChangesLabel(conversionCounts(conversionRows(args, args)).apply)
}

export function conversionsBannerDetail(
  counts: ConversionCounts,
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>,
  customerId: string | undefined
): string {
  return [
    accounts.get(customerId ?? "")?.label ?? null,
    counts.actions > 0 ? approvalCountLine(counts.actions, "conversion action") : null,
    counts.goals > 0 ? approvalCountLine(counts.goals, "account goal") : null,
  ]
    .filter((part) => part !== null)
    .join(" · ")
}

export function conversionsDetails(args: UpdateConversionsArgs | null): FanOutDetail[] {
  if (!args) return []
  const count = (kind: "action" | "goal") => args.items.filter((item) => item.kind === kind).length
  return [
    { label: "Conversion Actions", value: String(count("action")) },
    { label: "Account Goals", value: String(count("goal")) },
  ].filter((detail) => detail.value !== "0")
}
