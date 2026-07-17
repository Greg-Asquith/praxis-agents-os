// apps/web/src/features/files/search.ts

import type { FileSortDirection, FileSortField } from "@/features/files/types"

const FILE_SORT_FIELDS = new Set<FileSortField>([
  "created_at",
  "extension",
  "name",
  "processing_status",
  "size_bytes",
  "updated_at",
])

export type FilesSearch = {
  direction?: FileSortDirection
  fileId?: string
  page?: number
  sort?: FileSortField
}

export function validateFilesSearch(search: Record<string, unknown>): FilesSearch {
  const result: FilesSearch = {}

  if (typeof search["fileId"] === "string") {
    result.fileId = search["fileId"]
  }

  const page = Number(search["page"])
  if (Number.isSafeInteger(page) && page > 1) {
    result.page = page
  }

  const sort = search["sort"]
  if (typeof sort === "string" && FILE_SORT_FIELDS.has(sort as FileSortField)) {
    result.sort = sort as FileSortField
  }

  const direction = search["direction"]
  if (direction === "asc" || direction === "desc") {
    result.direction = direction
  }

  return result
}
