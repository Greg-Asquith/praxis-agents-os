// apps/web/src/integrations/airtable/record-data.ts

import { isUntrustedNode } from "@/components/tool-ui/untrusted-node"
import { isRecord } from "@/lib/guards"

export type AirtableRecord = {
  createdTime: string
  fields: Record<string, unknown>
  recordId: string
}

export function parseAirtableRecord(value: unknown): AirtableRecord | null {
  if (
    !isRecord(value) ||
    typeof value["record_id"] !== "string" ||
    !value["record_id"].trim() ||
    typeof value["created_time"] !== "string" ||
    !isRecord(value["fields"]) ||
    !isAirtableJson(value["fields"])
  ) {
    return null
  }
  return {
    createdTime: value["created_time"],
    fields: value["fields"],
    recordId: value["record_id"],
  }
}

export function isAirtableJson(value: unknown, depth = 0): boolean {
  if (depth > 12) {
    return false
  }
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    isUntrustedNode(value)
  ) {
    return true
  }
  if (Array.isArray(value)) {
    return value.every((item) => isAirtableJson(item, depth + 1))
  }
  return isRecord(value) && Object.values(value).every((item) => isAirtableJson(item, depth + 1))
}
