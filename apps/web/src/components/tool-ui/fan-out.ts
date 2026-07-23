// apps/web/src/components/tool-ui/fan-out.ts

import { isRecord } from "@/lib/guards"

export type FanOutEntry = {
  connectionId: string
  data: unknown
  displayName: string
  errorMessage: string | null
  externalId: string
  status: string
}

export type ParsedFanOutData<T> = {
  data: (T | null)[]
  entries: FanOutEntry[]
}

export function fanOutEntries(value: unknown): FanOutEntry[] | null {
  if (!isRecord(value) || !Array.isArray(value["results"])) {
    return null
  }
  const entries: FanOutEntry[] = []
  for (const item of value["results"]) {
    if (
      !isRecord(item) ||
      typeof item["connection_id"] !== "string" ||
      typeof item["display_name"] !== "string" ||
      typeof item["external_id"] !== "string" ||
      typeof item["status"] !== "string" ||
      (item["error_message"] !== null &&
        item["error_message"] !== undefined &&
        typeof item["error_message"] !== "string")
    ) {
      return null
    }
    entries.push({
      connectionId: item["connection_id"],
      data: item["data"],
      displayName: item["display_name"],
      errorMessage: typeof item["error_message"] === "string" ? item["error_message"] : null,
      externalId: item["external_id"],
      status: item["status"],
    })
  }
  return entries
}

export function parseFanOutData<T>(
  value: unknown,
  parse: (value: unknown) => T | null
): ParsedFanOutData<T> | null {
  const entries = fanOutEntries(value)
  if (!entries) {
    return null
  }
  const data = entries.map((entry) => (entry.status === "success" ? parse(entry.data) : null))
  if (entries.some((entry, index) => entry.status === "success" && data[index] === null)) {
    return null
  }
  return { data, entries }
}
