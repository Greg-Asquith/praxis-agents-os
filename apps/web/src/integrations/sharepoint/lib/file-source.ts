// apps/web/src/integrations/sharepoint/lib/file-source.ts

import { isPositiveInteger, isRecord, stringValue } from "@/lib/guards"

export type SharePointFileSource = { id: string; label: string }
export type SharePointSourceDetails = {
  id: string
  name: string
  contentType: string
  sizeBytes: number
}

export function sharePointFileSource(value: unknown): SharePointFileSource | null {
  if (!isRecord(value) || value["version"] !== 1 || value["entity_kind"] !== "file") return null
  const id = stringValue(value["entity_id"])
  const label = stringValue(value["label"])
  return id && label ? { id, label } : null
}

export function sharePointSourceDetails(value: unknown): SharePointSourceDetails | null {
  if (!isRecord(value)) return null
  const id = stringValue(value["file_id"])
  const name = stringValue(value["name"])
  const contentType = stringValue(value["content_type"])
  const sizeBytes = value["size_bytes"]
  return id && name && contentType && isPositiveInteger(sizeBytes)
    ? { id, name, contentType, sizeBytes }
    : null
}
