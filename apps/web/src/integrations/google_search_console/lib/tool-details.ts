// apps/web/src/integrations/google_search_console/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { compactDetails, listDetail, numberArg, stringArg } from "@/integrations/tool-details"
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
  const startDate = stringArg(args, "start_date")
  const endDate = stringArg(args, "end_date")
  const searchType = stringArg(args, "search_type") ?? DEFAULT_SEARCH_TYPE
  const filters = isRecord(args) ? filterSummary(args["filters"]) : null
  return compactDetails([
    startDate && endDate ? { label: "Range", value: `${startDate} → ${endDate}` } : null,
    listDetail(args, "dimensions", "Dimensions", (item) => titleCaseToken(item, item)),
    { label: "Search type", value: titleCaseToken(searchType, searchType) },
    filters ? { label: "Filters", summary: false, value: filters } : null,
    { label: "Row limit", value: String(numberArg(args, "row_limit") ?? DEFAULT_ROW_LIMIT) },
  ])
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
