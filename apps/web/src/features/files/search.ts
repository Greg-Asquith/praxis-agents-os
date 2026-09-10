// apps/web/src/features/files/search.ts

import type { FileScopeFilter, FileSortDirection, FileSortField } from "@/features/files/types"
import { isOneOf } from "@/lib/guards"

export const FILE_SORT_FIELDS = new Set<FileSortField>(["name", "size_bytes", "updated_at"])
const MAX_QUERY_LENGTH = 255

export type FilesSearch = {
  direction?: FileSortDirection
  fileId?: string
  folder?: string
  page?: number
  q?: string
  scope?: FileScopeFilter
  sort?: FileSortField
}

export function validateFilesSearch(search: Record<string, unknown>): FilesSearch {
  const result: FilesSearch = {}

  if (typeof search["fileId"] === "string") {
    result.fileId = search["fileId"]
  }
  if (typeof search["folder"] === "string") {
    result.folder = search["folder"]
  }

  const query = typeof search["q"] === "string" ? search["q"].trim().slice(0, MAX_QUERY_LENGTH) : ""
  if (query) {
    result.q = query
  }

  const scope = search["scope"]
  if (scope === "workspace" || scope === "platform") {
    result.scope = scope
  }

  const page = Number(search["page"])
  if (Number.isSafeInteger(page) && page > 1) {
    result.page = page
  }

  const sort = search["sort"]
  if (isOneOf(FILE_SORT_FIELDS, sort)) {
    result.sort = sort
  }

  const direction = search["direction"]
  if (direction === "asc" || direction === "desc") {
    result.direction = direction
  }

  return result
}
