// apps/web/src/integrations/airtable/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { isRecord } from "@/lib/guards"

export function airtableRecordDetails(args: unknown): FanOutDetail[] {
  if (!isRecord(args)) {
    return []
  }
  return compact([
    stringDetail(args, "table", "Table"),
    stringDetail(args, "record_id", "Record"),
    stringDetail(args, "view", "View"),
    stringDetail(args, "filter_by_formula", "Filter", false),
    numberDetail(args, "max_records", "Maximum records"),
  ])
}

function stringDetail(
  args: Record<string, unknown>,
  key: string,
  label: string,
  summary = true
): FanOutDetail | null {
  const value = args[key]
  if (typeof value !== "string" || !value.trim()) {
    return null
  }
  return { label, summary, value }
}

function numberDetail(
  args: Record<string, unknown>,
  key: string,
  label: string
): FanOutDetail | null {
  const value = args[key]
  return typeof value === "number" ? { label, value: String(value) } : null
}

function compact<T>(values: (T | null)[]): T[] {
  return values.filter((value): value is T => value !== null)
}
