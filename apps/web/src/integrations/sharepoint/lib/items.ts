// apps/web/src/integrations/sharepoint/lib/items.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import type { DataRow } from "@/components/ui/data-table-model"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export function itemRows(value: unknown): DataRow[] | null {
  if (!Array.isArray(value)) return null
  const rows: DataRow[] = []
  for (const item of value) {
    if (!isRecord(item)) return null
    const fields = ["name", "path", "content_type", "modified_at", "web_url"]
    const cells = fields.map((key) => nodeText(item[key]))
    const kind = item["kind"]
    const size = item["size_bytes"]
    if (
      cells.some((cell) => cell === null) ||
      (kind !== "file" && kind !== "folder") ||
      !isNonNegativeInteger(size)
    )
      return null
    rows.push({
      ...Object.fromEntries(fields.map((key, index) => [key, cells[index]])),
      kind: kind === "file" ? "File" : "Folder",
      size_bytes: size,
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
