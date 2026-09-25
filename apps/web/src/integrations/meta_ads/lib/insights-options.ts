// apps/web/src/integrations/meta_ads/lib/insights-options.ts

import { isNonNegativeInteger, isOneOf, isRecord, isStringArray } from "@/lib/guards"

const filterValueKinds = new Set(["scalar", "text", "number", "list"])

type ListOptions = { values: string[]; min: number; max: number }
type NumericOptions = { min: number; max: number }

export type InsightsOptions = {
  fields: ListOptions
  levels: string[]
  breakdowns: ListOptions
  actionBreakdowns: ListOptions
  attributionWindows: ListOptions
  intervals: (string | number)[]
  rows: NumericOptions
  filterFields: string[]
  filterOperators: string[]
  filterKinds: Record<string, string>
  maxFilters: number
  filterValues: NumericOptions
  sortDirections: string[]
  defaults: { level: string; interval: string | number; limit: number }
}

function shape(value: unknown, definitions: Record<string, unknown>): Record<string, unknown> {
  if (!isRecord(value)) throw new Error("Invalid form schema")
  const ref = value["$ref"]
  if (ref === undefined) return value
  if (typeof ref !== "string" || !ref.startsWith("#/$defs/"))
    throw new Error("Invalid schema reference")
  const definition = definitions[ref.slice("#/$defs/".length)]
  if (!isRecord(definition)) throw new Error("Invalid schema definition")
  return { ...definition, ...value }
}

function arrayShape(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) throw new Error("Invalid form schema")
  if (value["type"] === "array") return value
  const alternatives = value["anyOf"]
  if (!Array.isArray(alternatives)) throw new Error("Invalid array schema")
  const node: unknown = alternatives.find((item) => isRecord(item) && item["type"] === "array")
  if (!isRecord(node)) throw new Error("Invalid array schema")
  return node
}

function listOptions(value: unknown, source: "enum" | "examples" = "enum"): ListOptions {
  const node = arrayShape(value)
  const items = node["items"]
  if (!isRecord(items)) throw new Error("Invalid array items")
  const values = items[source]
  const min = node["minItems"] ?? 0
  const max = node["maxItems"]
  if (!isStringArray(values) || values.length === 0) throw new Error("Invalid form choices")
  if (!isNonNegativeInteger(min) || !isNonNegativeInteger(max))
    throw new Error("Invalid form bound")
  return { values, min, max }
}

/** Reads choices and bounds supplied by the tool-presentations API. */
export function parseInsightsOptions(value: unknown): InsightsOptions | null {
  try {
    if (!isRecord(value)) return null
    const definitions = value["$defs"]
    const properties = value["properties"]
    if (!isRecord(definitions) || !isRecord(properties)) return null
    const level = shape(properties["level"], definitions)
    const interval = properties["time_increment"]
    if (!isRecord(interval)) return null
    const variants = interval["anyOf"]
    if (!Array.isArray(variants)) return null
    const intervals = variants.flatMap((raw): (string | number)[] => {
      if (!isRecord(raw)) throw new Error("Invalid interval schema")
      const choices = raw["enum"]
      if (choices) {
        if (!isStringArray(choices) || choices.length === 0)
          throw new Error("Invalid interval choices")
        return choices
      }
      const min = raw["minimum"]
      const max = raw["maximum"]
      if (!isNonNegativeInteger(min) || !isNonNegativeInteger(max) || max < min || max - min > 1000)
        throw new Error("Invalid interval range")
      return Array.from({ length: max - min + 1 }, (_, index) => min + index)
    })
    const limit = properties["limit"]
    if (!isRecord(limit)) return null
    const filters = arrayShape(properties["filters"])
    const filter = shape(filters["items"], definitions)["properties"]
    if (!isRecord(filter)) return null
    const operators = shape(filter["operator"], definitions)
    const kinds = operators["x-value-kinds"]
    if (!isRecord(kinds)) return null
    const filterKinds: Record<string, string> = {}
    for (const [key, kind] of Object.entries(kinds)) {
      if (!isOneOf(filterValueKinds, kind)) return null
      filterKinds[key] = kind
    }
    const defaultLevel = level["default"]
    const defaultInterval = interval["default"]
    const defaultLimit = limit["default"]
    if (
      typeof defaultLevel !== "string" ||
      (typeof defaultInterval !== "string" && typeof defaultInterval !== "number") ||
      !isNonNegativeInteger(defaultLimit)
    )
      return null
    const values = arrayShape(filter["value"])
    const rowMin = limit["minimum"]
    const rowMax = limit["maximum"]
    const maxFilters = filters["maxItems"]
    const valueMin = values["minItems"]
    const valueMax = values["maxItems"]
    if (
      !isNonNegativeInteger(rowMin) ||
      !isNonNegativeInteger(rowMax) ||
      !isNonNegativeInteger(maxFilters) ||
      !isNonNegativeInteger(valueMin) ||
      !isNonNegativeInteger(valueMax)
    )
      return null
    const field = filter["field"]
    const sort = properties["sort"]
    if (!isRecord(field) || !isRecord(sort)) return null
    const levels = level["enum"]
    const filterFields = field["examples"]
    const filterOperators = operators["enum"]
    const sortDirections = sort["x-directions"]
    if (
      !isStringArray(levels) ||
      levels.length === 0 ||
      !isStringArray(filterFields) ||
      filterFields.length === 0 ||
      !isStringArray(filterOperators) ||
      filterOperators.length === 0 ||
      !isStringArray(sortDirections) ||
      sortDirections.length === 0
    )
      return null
    const options: InsightsOptions = {
      fields: listOptions(properties["fields"], "examples"),
      levels,
      breakdowns: listOptions(properties["breakdowns"]),
      actionBreakdowns: listOptions(properties["action_breakdowns"]),
      attributionWindows: listOptions(properties["attribution_windows"]),
      intervals,
      rows: { min: rowMin, max: rowMax },
      filterFields,
      filterOperators,
      filterKinds,
      maxFilters,
      filterValues: { min: valueMin, max: valueMax },
      sortDirections,
      defaults: { level: defaultLevel, interval: defaultInterval, limit: defaultLimit },
    }
    if (
      !options.levels.includes(defaultLevel) ||
      !intervals.includes(defaultInterval) ||
      options.filterOperators.some((operator) => !filterKinds[operator])
    )
      return null
    return options
  } catch {
    return null
  }
}
