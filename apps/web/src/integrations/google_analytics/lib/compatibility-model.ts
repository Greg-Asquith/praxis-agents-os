// apps/web/src/integrations/google_analytics/lib/compatibility-model.ts

import { isRecord } from "@/lib/guards"

type GoogleAnalyticsFieldCompatibility = {
  apiName: string
  compatible: boolean
}

export type GoogleAnalyticsCompatibility = {
  compatible: boolean
  fields: GoogleAnalyticsFieldCompatibility[]
  incompatibleFields: string[]
}

export function parseCompatibility(value: unknown): GoogleAnalyticsCompatibility | null {
  if (
    !isRecord(value) ||
    typeof value["compatible"] !== "boolean" ||
    !Array.isArray(value["dimensions"]) ||
    !Array.isArray(value["metrics"]) ||
    !Array.isArray(value["incompatible_fields"])
  )
    return null
  const dimensions = parseFields(value["dimensions"])
  const metrics = parseFields(value["metrics"])
  const incompatibleFields = value["incompatible_fields"]
  if (
    !dimensions ||
    !metrics ||
    !incompatibleFields.every((item): item is string => typeof item === "string")
  )
    return null
  if (value["compatible"] !== (incompatibleFields.length === 0)) return null
  return {
    compatible: value["compatible"],
    fields: [...dimensions, ...metrics],
    incompatibleFields,
  }
}

function parseFields(values: unknown[]): GoogleAnalyticsFieldCompatibility[] | null {
  const fields: GoogleAnalyticsFieldCompatibility[] = []
  for (const value of values) {
    if (
      !isRecord(value) ||
      typeof value["api_name"] !== "string" ||
      (value["compatibility"] !== "COMPATIBLE" && value["compatibility"] !== "INCOMPATIBLE")
    )
      return null
    fields.push({ apiName: value["api_name"], compatible: value["compatibility"] === "COMPATIBLE" })
  }
  return fields
}
