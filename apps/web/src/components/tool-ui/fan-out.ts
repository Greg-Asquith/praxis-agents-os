// apps/web/src/components/tool-ui/fan-out.ts

import { isRecord } from "@/lib/guards"

export type FanOutEntry = {
  data: unknown
  displayName: string
  errorCode?: string | null
  errorMessage: string | null
  externalId: string
  providerKey: string
  renderKey: string
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
  for (const [index, item] of value["results"].entries()) {
    if (
      !isRecord(item) ||
      typeof item["provider_key"] !== "string" ||
      typeof item["display_name"] !== "string" ||
      typeof item["external_id"] !== "string" ||
      (item["status"] !== "success" && item["status"] !== "error") ||
      (item["error_code"] !== null &&
        item["error_code"] !== undefined &&
        typeof item["error_code"] !== "string") ||
      (item["error_message"] !== null &&
        item["error_message"] !== undefined &&
        typeof item["error_message"] !== "string")
    ) {
      return null
    }
    entries.push({
      data: item["data"],
      displayName: item["display_name"],
      errorCode: typeof item["error_code"] === "string" ? item["error_code"] : null,
      errorMessage: typeof item["error_message"] === "string" ? item["error_message"] : null,
      externalId: item["external_id"],
      providerKey: item["provider_key"],
      renderKey: `${item["provider_key"]}:${item["external_id"]}:${String(index)}`,
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
