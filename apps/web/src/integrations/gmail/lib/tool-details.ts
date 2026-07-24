// apps/web/src/integrations/gmail/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { isRecord } from "@/lib/guards"

export function gmailSearchDetails(args: unknown): FanOutDetail[] {
  const query = stringArg(args, "query")
  const limit = numberArg(args, "limit") ?? 10
  return [
    ...(query ? [{ label: "Search", value: query }] : []),
    { label: "Results", value: `Up to ${String(limit)} messages` },
  ]
}

export function gmailSendDetails(args: unknown): FanOutDetail[] {
  return compact([
    listArg(args, "to", "To"),
    stringDetail(args, "subject", "Subject"),
    stringDetail(args, "body_text", "Message", false),
    listArg(args, "cc", "Cc"),
    listArg(args, "bcc", "Bcc"),
  ])
}

function stringDetail(
  args: unknown,
  key: string,
  label: string,
  summary = true
): FanOutDetail | null {
  const value = stringArg(args, key)
  return value ? { label, summary, value } : null
}

function listArg(args: unknown, key: string, label: string): FanOutDetail | null {
  if (!isRecord(args) || !Array.isArray(args[key])) {
    return null
  }
  const values = args[key].filter((value): value is string => typeof value === "string")
  return values.length > 0 ? { label, value: values.join(", ") } : null
}

function stringArg(args: unknown, key: string): string | null {
  if (!isRecord(args) || typeof args[key] !== "string") {
    return null
  }
  const value = args[key].trim()
  return value || null
}

function numberArg(args: unknown, key: string): number | null {
  return isRecord(args) && typeof args[key] === "number" ? args[key] : null
}

function compact<T>(values: (T | null)[]): T[] {
  return values.filter((value): value is T => value !== null)
}
