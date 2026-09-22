// apps/web/src/integrations/sharepoint/lib/items.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import type { DataRow } from "@/components/ui/data-table-model"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

type SharePointItem = {
  name: string
  path: string
  contentType: string
  modifiedAt: string
  webUrl: string
  kind: "file" | "folder"
  sizeBytes: number
}

function itemTextFields(item: Record<string, unknown>) {
  const name = nodeText(item["name"])
  const path = nodeText(item["path"])
  const contentType = nodeText(item["content_type"])
  const modifiedAt = nodeText(item["modified_at"])
  const webUrl = nodeText(item["web_url"])
  if (
    name === null ||
    path === null ||
    contentType === null ||
    modifiedAt === null ||
    webUrl === null
  )
    return null
  return { name, path, contentType, modifiedAt, webUrl }
}

export function sharePointItem(value: unknown): SharePointItem | null {
  if (!isRecord(value)) return null
  const text = itemTextFields(value)
  const kind = value["kind"]
  const sizeBytes = value["size_bytes"]
  if (!text || (kind !== "file" && kind !== "folder") || !isNonNegativeInteger(sizeBytes))
    return null
  return { ...text, kind, sizeBytes }
}

export function itemRows(value: unknown): DataRow[] | null {
  if (!Array.isArray(value)) return null
  const rows: DataRow[] = []
  for (const rawItem of value) {
    const item = sharePointItem(rawItem)
    if (!item) return null
    rows.push({
      name: item.name,
      path: item.path,
      content_type: item.contentType,
      modified_at: item.modifiedAt,
      web_url: item.webUrl,
      kind: item.kind === "file" ? "File" : "Folder",
      size_bytes: item.sizeBytes,
    })
  }
  return rows
}

export function folderResult(value: unknown) {
  if (
    !isRecord(value) ||
    !isNonNegativeInteger(value["count"]) ||
    typeof value["has_more"] !== "boolean"
  )
    return null
  const rows = itemRows(value["items"])
  if (rows === null || rows.length > 200 || value["count"] !== rows.length) return null
  return { rows, hasMore: value["has_more"] }
}

export function searchResult(value: unknown): DataRow[] | null {
  if (!isRecord(value) || !isNonNegativeInteger(value["count"])) return null
  const rows = itemRows(value["items"])
  if (rows === null || rows.length > 25 || value["count"] !== rows.length) return null
  return rows
}
