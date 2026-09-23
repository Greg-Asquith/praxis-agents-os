// apps/web/src/components/tool-ui/result-preview.ts

import { isNonNegativeInteger, isRecord } from "@/lib/guards"

const FILE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export type ResultPreview = {
  data: unknown
  fileId: string
  lists: { path: string; shown: number; total: number }[]
}

export function parseResultPreview(value: unknown): ResultPreview | null {
  if (!isRecord(value) || value["preview"] !== true) return null
  const fileId = value["file_id"]
  const reference = value["file_reference"]
  if (
    typeof fileId !== "string" ||
    !FILE_ID.test(fileId) ||
    typeof value["file_name"] !== "string" ||
    !isRecord(reference) ||
    reference["entity_kind"] !== "file" ||
    reference["version"] !== 1 ||
    reference["entity_id"] !== fileId ||
    !isRecord(value["lists"])
  )
    return null

  const lists: ResultPreview["lists"] = []
  for (const [path, count] of Object.entries(value["lists"])) {
    if (
      !isRecord(count) ||
      !isNonNegativeInteger(count["shown"]) ||
      !isNonNegativeInteger(count["total"]) ||
      count["shown"] > count["total"] ||
      resultListLength(value["data"], path) !== count["shown"]
    )
      return null
    lists.push({ path, shown: count["shown"], total: count["total"] })
  }
  if (lists.length === 0) return null
  return {
    data: value["data"],
    fileId,
    lists,
  }
}

export function resultListLength(data: unknown, path: string): number | null {
  let value = data
  for (const key of path === "$" ? [] : path.split(".")) {
    if (Array.isArray(value) && /^(0|[1-9]\d*)$/.test(key)) {
      value = value[Number(key)]
    } else if (isRecord(value) && Object.hasOwn(value, key)) {
      value = value[key]
    } else {
      return null
    }
  }
  return Array.isArray(value) ? value.length : null
}
