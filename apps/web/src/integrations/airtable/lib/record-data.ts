// apps/web/src/integrations/airtable/lib/record-data.ts

import { isUntrustedNode } from "@/components/tool-ui/untrusted-node"
import { isRecord } from "@/lib/guards"

export type AirtableRecord = {
  createdTime: string
  fields: Record<string, unknown>
  recordId: string
}

export type AirtableRecordList = {
  records: AirtableRecord[]
  total: number
}

export type AirtableWriteAction = "create" | "update"

export type AirtableWriteArgs = {
  fields: Record<string, unknown>
  recordId: string | null
  table: string
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

export function parseAirtableRecordList(value: unknown): AirtableRecordList | null {
  if (!isRecord(value) || !Array.isArray(value["records"]) || typeof value["total"] !== "number") {
    return null
  }
  const records = value["records"].map(parseAirtableRecord)
  return records.every((record): record is AirtableRecord => record !== null)
    ? { records, total: value["total"] }
    : null
}

export function parseAirtableWriteArgs(
  value: unknown,
  action: AirtableWriteAction
): AirtableWriteArgs | null {
  if (
    !isRecord(value) ||
    typeof value["table"] !== "string" ||
    !isRecord(value["fields"]) ||
    Object.keys(value["fields"]).length === 0 ||
    !isAirtableJson(value["fields"]) ||
    (action === "update" && typeof value["record_id"] !== "string")
  ) {
    return null
  }
  return {
    fields: value["fields"],
    recordId: typeof value["record_id"] === "string" ? value["record_id"] : null,
    table: value["table"],
  }
}

export function parseAirtableRecordId(value: unknown): string | null {
  return isRecord(value) && typeof value["record_id"] === "string" && value["record_id"].trim()
    ? value["record_id"]
    : null
}

function isAirtableJson(value: unknown, depth = 0): boolean {
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
