// apps/web/src/components/data-table/server-state.ts

import type { PaginationState, SortingState } from "@tanstack/react-table"

import { clampPaginationOffset } from "@/components/ui/pagination-controls"
import { isOneOf } from "@/lib/guards"

type ServerPaginationParams = {
  limit: number
  offset: number
}

type ServerSortDirection = "asc" | "desc"

type ServerSortParams<TField extends string = string> = {
  sort_by: TField
  sort_direction: ServerSortDirection
}

export function paginationStateFromServer(
  params: ServerPaginationParams,
  total: number
): PaginationState {
  return {
    pageIndex: Math.floor(clampPaginationOffset(total, params.offset, params.limit) / params.limit),
    pageSize: params.limit,
  }
}

export function paginationStateToServer(state: PaginationState): ServerPaginationParams {
  return {
    limit: state.pageSize,
    offset: Math.max(0, Math.floor(state.pageIndex)) * state.pageSize,
  }
}

export function sortingStateFromServer<TField extends string>(
  params: ServerSortParams<TField>
): SortingState {
  return [{ id: params.sort_by, desc: params.sort_direction === "desc" }]
}

export function sortingStateToServer<TField extends string>(
  state: SortingState,
  validFields: ReadonlySet<TField>,
  fallback: ServerSortParams<TField>
): ServerSortParams<TField> {
  const firstSort = state[0]
  if (!firstSort || !isOneOf(validFields, firstSort.id)) {
    return fallback
  }

  return {
    sort_by: firstSort.id,
    sort_direction: firstSort.desc ? "desc" : "asc",
  }
}
