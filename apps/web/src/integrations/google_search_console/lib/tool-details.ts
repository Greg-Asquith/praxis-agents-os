// apps/web/src/integrations/google_search_console/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const OPERATOR_LABELS: Record<string, string> = {
  contains: "contains",
  equals: "is",
  excludingRegex: "does not match",
  includingRegex: "matches",
  notContains: "does not contain",
  notEquals: "is not",
}
const DEFAULT_SEARCH_TYPE = "web"
const DEFAULT_ROW_LIMIT = 100

export function searchAnalyticsDetails(args: unknown): FanOutDetail[] {
  if (!isRecord(args)) return []
  const details: FanOutDetail[] = []
  if (typeof args["start_date"] === "string" && typeof args["end_date"] === "string") {
    details.push({ label: "Range", value: `${args["start_date"]} → ${args["end_date"]}` })
  }
  const dimensions = args["dimensions"]
  if (
    Array.isArray(dimensions) &&
    dimensions.length > 0 &&
    dimensions.every((item): item is string => typeof item === "string")
  ) {
    details.push({
      label: "Dimensions",
      value: dimensions.map((item) => titleCaseToken(item, item)).join(", "),
    })
  }
  const searchType =
    typeof args["search_type"] === "string" ? args["search_type"] : DEFAULT_SEARCH_TYPE
  details.push({
    label: "Search type",
    value: titleCaseToken(searchType, searchType),
  })
  const filters = filterSummary(args["filters"])
  if (filters) {
    details.push({ label: "Filters", summary: false, value: filters })
  }
  const rowLimit = typeof args["row_limit"] === "number" ? args["row_limit"] : DEFAULT_ROW_LIMIT
  details.push({ label: "Row limit", value: String(rowLimit) })
  return details
}

function filterSummary(value: unknown): string | null {
  if (!Array.isArray(value)) return null
  const filters = value.flatMap((item) => {
    if (
      !isRecord(item) ||
      typeof item["dimension"] !== "string" ||
      typeof item["operator"] !== "string" ||
      typeof item["expression"] !== "string"
    ) {
      return []
    }
    const operator = OPERATOR_LABELS[item["operator"]] ?? item["operator"]
    return `${titleCaseToken(item["dimension"], item["dimension"])} ${operator} ${item["expression"]}`
  })
  return filters.length > 0 ? filters.join("; ") : null
}
