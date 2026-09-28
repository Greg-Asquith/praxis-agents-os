// apps/web/src/integrations/meta_ads/lib/insights-model.ts

import type { DataColumn, DataRow } from "@/components/ui/data-table"
import { UNRESOLVED_CONVERSION_NAME } from "@/integrations/meta_ads/lib/read-models"
import { titleCaseToken } from "@/lib/format"
import {
  isDateString,
  isNonNegativeInteger,
  isNullableFiniteNumber,
  isNullableString,
  isOneOf,
  isRecord,
} from "@/lib/guards"

export type MetaAdsInsights = {
  columns: DataColumn[]
  rows: DataRow[]
  notes: string[]
  currency: string
  timezone: string
  mode: "direct" | "background"
  truncationNote: string | null
}

// The backend owns which requested fields are amounts in the account currency.
type MoneyFormat = { currency: string; fields: ReadonlySet<string> }

const LEVELS = new Set(["account", "campaign", "adset", "ad"])
const MODES: ReadonlySet<MetaAdsInsights["mode"]> = new Set(["direct", "background"])

export function parseMetaAdsInsights(value: unknown): MetaAdsInsights | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["rows"]) ||
    !isNonNegativeInteger(value["row_count"]) ||
    value["row_count"] < value["rows"].length ||
    typeof value["truncated"] !== "boolean" ||
    !isNullableString(value["truncation_note"]) ||
    !isOneOf(MODES, value["mode"]) ||
    !isOneOf(LEVELS, value["level"]) ||
    !isDateString(value["since"]) ||
    !isDateString(value["until"]) ||
    value["since"] > value["until"] ||
    typeof value["currency"] !== "string" ||
    (value["currency"] !== "" && !/^[A-Z]{3}$/.test(value["currency"])) ||
    !Array.isArray(value["money_fields"]) ||
    !value["money_fields"].every((field): field is string => typeof field === "string") ||
    typeof value["timezone_name"] !== "string" ||
    !Array.isArray(value["notes"]) ||
    !value["notes"].every((note): note is string => typeof note === "string")
  )
    return null

  const money: MoneyFormat = { currency: value["currency"], fields: new Set(value["money_fields"]) }
  const keyColumns = new Map<string, DataColumn>()
  const metricColumns = new Map<string, DataColumn>()
  const actionColumns = new Map<string, DataColumn>()
  const rows: DataRow[] = []
  for (const raw of value["rows"]) {
    if (
      !isRecord(raw) ||
      !isRecord(raw["keys"]) ||
      !isRecord(raw["metrics"]) ||
      !isRecord(raw["actions"]) ||
      !isDateString(raw["date_start"]) ||
      !isDateString(raw["date_stop"])
    )
      return null
    const row: DataRow = { date_start: raw["date_start"], date_stop: raw["date_stop"] }
    for (const [name, item] of Object.entries(raw["keys"])) {
      if (!isNullableString(item)) return null
      const key = `keys.${name}`
      row[key] = item
      keyColumns.set(key, {
        key,
        label: titleCaseToken(name, name),
        kind: name.endsWith("_id") ? "id" : "text",
      })
    }
    for (const [name, item] of Object.entries(raw["metrics"])) {
      if (!isNullableFiniteNumber(item)) return null
      const key = `metrics.${name}`
      row[key] = item
      metricColumns.set(key, metricColumn(key, name, titleCaseToken(name, name), money))
    }
    if (!parseActions(raw["actions"], row, actionColumns, money)) return null
    rows.push(row)
  }
  return {
    columns: [
      ...keyColumns.values(),
      { key: "date_start", label: "Date start", kind: "date" },
      { key: "date_stop", label: "Date end", kind: "date" },
      ...metricColumns.values(),
      ...actionColumns.values(),
    ],
    rows,
    notes: value["notes"],
    currency: value["currency"],
    timezone: value["timezone_name"],
    mode: value["mode"],
    truncationNote: value["truncation_note"],
  }
}

function parseActions(
  actions: Record<string, unknown>,
  row: DataRow,
  columns: Map<string, DataColumn>,
  money: MoneyFormat
): boolean {
  for (const [field, items] of Object.entries(actions)) {
    if (!Array.isArray(items)) return false
    for (const item of items) {
      if (
        !isRecord(item) ||
        typeof item["action_type"] !== "string" ||
        !isNullableFiniteNumber(item["value"]) ||
        !isRecord(item["windows"]) ||
        !validCustomConversion(item)
      )
        return false
      const breakdowns = parseActionBreakdowns(item["breakdowns"])
      if (!breakdowns) return false
      const suffix =
        breakdowns.length > 0 ? `.${encodeURIComponent(JSON.stringify(breakdowns))}` : ""
      const key = `actions.${field}.${item["action_type"]}${suffix}`
      if (Object.hasOwn(row, key)) return false
      const context = breakdowns
        .map(([name, value]) => `${titleCaseToken(name, name)}: ${value ?? "Not available"}`)
        .join(", ")
      const actionLabel =
        customConversionLabel(item) ?? titleCaseToken(item["action_type"], item["action_type"])
      const label = `${titleCaseToken(field, field)}: ${actionLabel}${context ? ` (${context})` : ""}`
      row[key] = item["value"]
      columns.set(key, metricColumn(key, field, label, money))
      for (const [window, amount] of Object.entries(item["windows"])) {
        if (!isNullableFiniteNumber(amount)) return false
        const windowKey = `${key}.${window}`
        row[windowKey] = amount
        columns.set(
          windowKey,
          metricColumn(windowKey, field, `${label} (${titleCaseToken(window, window)})`, money)
        )
      }
    }
  }
  return true
}

function parseActionBreakdowns(value: unknown): [string, string | null][] | null {
  if (value === undefined) return []
  if (!isRecord(value)) return null
  const entries: [string, string | null][] = []
  for (const [name, item] of Object.entries(value)) {
    if (!isNullableString(item)) return null
    entries.push([name, item])
  }
  return entries.sort(([left], [right]) => left.localeCompare(right))
}

function metricColumn(key: string, field: string, label: string, money: MoneyFormat): DataColumn {
  const kind = money.fields.has(field)
    ? "currency"
    : field === "ctr" || field.endsWith("_ctr")
      ? "percent"
      : "number"
  return {
    key,
    kind,
    label,
    ...(kind === "currency" ? { currencyCode: money.currency } : {}),
    ...(kind === "percent" ? { unit: "percentage-points" as const } : {}),
  }
}

function customConversionLabel(item: Record<string, unknown>): string | null {
  const id =
    typeof item["custom_conversion_id"] === "string"
      ? item["custom_conversion_id"]
      : typeof item["action_type"] === "string"
        ? /^offsite_conversion\.custom\.(\d+)$/.exec(item["action_type"])?.[1]
        : undefined
  if (!id) return null
  const name =
    typeof item["custom_conversion_name"] === "string" && item["custom_conversion_name"].trim()
      ? item["custom_conversion_name"]
      : UNRESOLVED_CONVERSION_NAME
  return `${name} (ID: ${id})`
}

// A name requires an ID, and the ID must match the action type it came from.
function validCustomConversion(item: Record<string, unknown>): boolean {
  const id = item["custom_conversion_id"]
  const name = item["custom_conversion_name"]
  const hasName = name !== undefined && name !== null
  if (id === undefined || id === null) return !hasName
  return (
    typeof id === "string" &&
    /^[0-9]{1,128}$/.test(id) &&
    item["action_type"] === `offsite_conversion.custom.${id}` &&
    (!hasName || (typeof name === "string" && name.length <= 512))
  )
}
