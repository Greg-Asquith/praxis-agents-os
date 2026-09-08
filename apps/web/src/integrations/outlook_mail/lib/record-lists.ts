// apps/web/src/integrations/outlook_mail/lib/record-lists.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import type { DataRow } from "@/components/ui/data-table-model"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

function rows(
  value: unknown,
  key: string,
  parse: (item: Record<string, unknown>) => DataRow | null
): DataRow[] | null {
  if (!isRecord(value) || !Array.isArray(value[key])) return null
  const result: DataRow[] = []
  for (const item of value[key]) {
    if (!isRecord(item)) return null
    const row = parse(item)
    if (row === null) return null
    result.push(row)
  }
  return result
}

export function folderRows(value: unknown): DataRow[] | null {
  return rows(value, "folders", (item) => {
    const name = nodeText(item["name"])
    const unread = item["unread_count"]
    const total = item["total_count"]
    const children = item["child_folder_count"]
    if (
      name === null ||
      !isNonNegativeInteger(unread) ||
      !isNonNegativeInteger(total) ||
      !isNonNegativeInteger(children)
    )
      return null
    return { name, unread_count: unread, total_count: total, child_folder_count: children }
  })
}

export function peopleRows(value: unknown): DataRow[] | null {
  return rows(value, "people", (item) => {
    const fields = ["name", "address", "job_title", "department"]
    const cells = fields.map((key) => nodeText(item[key]))
    if (cells.some((cell) => cell === null)) return null
    return Object.fromEntries(fields.map((key, index) => [key, cells[index]]))
  })
}
