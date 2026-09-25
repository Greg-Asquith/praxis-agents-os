// apps/web/src/integrations/meta_ads/lib/insights-approval.ts

import { isRecord, isStringArray } from "@/lib/guards"

import type { InsightsOptions } from "@/integrations/meta_ads/lib/insights-options"

export type InsightsFilter = {
  field: string
  operator: string
  value: string | number | (string | number)[]
}

export type InsightsApprovalArgs = {
  since: string
  until: string
  level: string
  fields: string[]
  breakdowns: string[]
  action_breakdowns: string[]
  attribution_windows: string[]
  time_increment: string | number
  limit: number
  sort: string
  filters: InsightsFilter[]
}

export function parseInsightsApproval(
  value: unknown,
  options: InsightsOptions
): InsightsApprovalArgs | null {
  if (
    !isRecord(value) ||
    typeof value["since"] !== "string" ||
    typeof value["until"] !== "string" ||
    !isStringArray(value["fields"])
  )
    return null
  const level = value["level"] ?? options.defaults.level
  const breakdowns = value["breakdowns"] ?? []
  const actions = value["action_breakdowns"] ?? []
  const windows = value["attribution_windows"] ?? []
  const interval = value["time_increment"] ?? options.defaults.interval
  const limit = value["limit"] ?? options.defaults.limit
  const sort = value["sort"] ?? ""
  const filters = value["filters"] ?? []
  if (
    typeof level !== "string" ||
    !isStringArray(breakdowns) ||
    !isStringArray(actions) ||
    !isStringArray(windows) ||
    (typeof interval !== "string" && typeof interval !== "number") ||
    typeof limit !== "number" ||
    typeof sort !== "string" ||
    !Array.isArray(filters)
  )
    return null
  const rows: InsightsFilter[] = []
  for (const row of filters) {
    if (
      !isRecord(row) ||
      Object.keys(row).some((key) => !["field", "operator", "value"].includes(key)) ||
      typeof row["field"] !== "string" ||
      typeof row["operator"] !== "string"
    )
      return null
    const cell: unknown = row["value"]
    const scalar = (entry: unknown): entry is string | number =>
      typeof entry === "string" || (typeof entry === "number" && Number.isFinite(entry))
    if (scalar(cell) || (Array.isArray(cell) && cell.every(scalar)))
      rows.push({ field: row["field"], operator: row["operator"], value: cell })
    else return null
  }
  return {
    since: value["since"],
    until: value["until"],
    fields: value["fields"],
    level,
    breakdowns,
    action_breakdowns: actions,
    attribution_windows: windows,
    time_increment: interval,
    limit,
    sort,
    filters: rows,
  }
}

export function insightsApprovalError(
  args: InsightsApprovalArgs | null,
  options: InsightsOptions
): string | null {
  if (!args)
    return "The report options could not be read. Decline this request and ask for the report again."
  for (const date of [args.since, args.until]) {
    const parsed = new Date(`${date}T00:00:00Z`)
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
      Number.isNaN(parsed.getTime()) ||
      parsed.toISOString().slice(0, 10) !== date
    )
      return "Choose valid start and end dates."
  }
  if (args.since > args.until) return "The end date must be on or after the start date."
  if (!options.levels.includes(args.level)) return "Choose a reporting level."
  if (
    args.fields.length < options.fields.min ||
    args.fields.length > options.fields.max ||
    args.fields.some((field) => !/^[a-z0-9_]+$/.test(field))
  )
    return `Choose between ${String(options.fields.min)} and ${String(options.fields.max)} report fields.`
  for (const [values, choices, label] of [
    [args.breakdowns, options.breakdowns, "breakdowns"],
    [args.action_breakdowns, options.actionBreakdowns, "action breakdowns"],
    [args.attribution_windows, options.attributionWindows, "attribution windows"],
  ] as const) {
    if (values.length > choices.max || values.some((item) => !choices.values.includes(item)))
      return `Choose supported ${label} (up to ${String(choices.max)}).`
  }
  if (
    !Number.isInteger(args.limit) ||
    args.limit < options.rows.min ||
    args.limit > options.rows.max
  )
    return `Enter a whole number between ${String(options.rows.min)} and ${String(options.rows.max)} for maximum rows.`
  if (!options.intervals.includes(args.time_increment)) return "Choose a supported report interval."
  if (
    args.sort &&
    !args.fields.some((field) =>
      options.sortDirections.some((direction) => args.sort === `${field}_${direction}`)
    )
  )
    return "Choose a sort order for a selected report field."
  if (args.filters.length > options.maxFilters)
    return `Use up to ${String(options.maxFilters)} filters.`
  for (const row of args.filters) {
    const kind = options.filterKinds[row.operator]
    const value = row.value
    if (typeof value === "string" && !value.trim()) return "Enter a value for each filter."
    if (!args.fields.includes(row.field) && !options.filterFields.includes(row.field))
      return "Choose a supported field for each filter."
    if (!options.filterOperators.includes(row.operator)) return "Choose a filter condition."
    if ((kind === "list") !== Array.isArray(value))
      return "Use the value type required by the filter condition."
    if (
      Array.isArray(value) &&
      (value.length < options.filterValues.min || value.length > options.filterValues.max)
    )
      return `Enter between ${String(options.filterValues.min)} and ${String(options.filterValues.max)} filter values.`
    if (kind === "number" && typeof value !== "number")
      return "Enter a number for this filter condition."
    if (kind === "text" && typeof value !== "string") return "Enter text for this filter condition."
  }
  return null
}
