// apps/web/src/components/data-table/pagination-model.ts

import { clampPaginationOffset } from "@/components/ui/pagination-controls"

export function pageIndexToOffset(pageIndex: number, pageSize: number) {
  return Math.max(0, Math.floor(pageIndex)) * pageSize
}

export function offsetToPageIndex(offset: number, pageSize: number, total: number) {
  return Math.floor(clampPaginationOffset(total, offset, pageSize) / pageSize)
}
