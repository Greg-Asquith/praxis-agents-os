// apps/web/src/integrations/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { isRecord } from "@/lib/guards"

// Readers accept the raw tool arguments so presenters never repeat the record checks.
export function stringArg(args: unknown, key: string): string | null {
  if (!isRecord(args) || typeof args[key] !== "string") {
    return null
  }
  const value = args[key].trim()
  return value || null
}

export function numberArg(args: unknown, key: string): number | null {
  return isRecord(args) && typeof args[key] === "number" ? args[key] : null
}

export function booleanArg(args: unknown, key: string): boolean | null {
  return isRecord(args) && typeof args[key] === "boolean" ? args[key] : null
}

function stringListArg(args: unknown, key: string): string[] {
  if (!isRecord(args) || !Array.isArray(args[key])) {
    return []
  }
  return args[key].filter((item): item is string => typeof item === "string")
}

export function stringDetail(
  args: unknown,
  key: string,
  label: string,
  summary?: boolean
): FanOutDetail | null {
  const value = stringArg(args, key)
  if (value === null) {
    return null
  }
  return summary === undefined ? { label, value } : { label, summary, value }
}

export function numberDetail(args: unknown, key: string, label: string): FanOutDetail | null {
  const value = numberArg(args, key)
  return value === null ? null : { label, value: String(value) }
}

export function listDetail(
  args: unknown,
  key: string,
  label: string,
  format: (value: string) => string = (value) => value
): FanOutDetail | null {
  const values = stringListArg(args, key)
  return values.length > 0 ? { label, value: values.map(format).join(", ") } : null
}

export function compactDetails(details: (FanOutDetail | null)[]): FanOutDetail[] {
  return details.filter((detail): detail is FanOutDetail => detail !== null)
}
