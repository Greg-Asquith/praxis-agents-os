// apps/web/src/features/files/search.ts

import type { FileSortField } from "@/features/files/types"
import { validateListSearch, type ListSearch } from "@/lib/list-search"

export const FILE_SORT_FIELDS = new Set<FileSortField>(["name", "size_bytes", "updated_at"])

export type FilesSearch = ListSearch<FileSortField> & {
  fileId?: string
  folder?: string
}

export function validateFilesSearch(search: Record<string, unknown>): FilesSearch {
  return {
    ...validateListSearch(search, FILE_SORT_FIELDS),
    ...(typeof search["fileId"] === "string" ? { fileId: search["fileId"] } : {}),
    ...(typeof search["folder"] === "string" ? { folder: search["folder"] } : {}),
  }
}
