// apps/web/src/features/artifacts/routes/artifacts-route.tsx

import { useCallback, useState } from "react"
import type { OnChangeFn, PaginationState, SortingState } from "@tanstack/react-table"

import { PageHeader } from "@/components/shell/page-header"
import { useDebouncedValue } from "@/components/tool-ui/use-debounced-value"
import { useArtifactsQuery } from "@/features/artifacts/api/list-artifacts"
import { ArtifactsTable } from "@/features/artifacts/components/artifacts-table"
import type { ArtifactSortField } from "@/features/artifacts/types"

const PAGE_SIZE = 25
const SEARCH_DEBOUNCE_MS = 250

export function ArtifactsRoute() {
  const [globalFilter, setGlobalFilter] = useState("")
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: PAGE_SIZE,
  })
  const [sorting, setSorting] = useState<SortingState>([{ id: "updated_at", desc: true }])
  const search = useDebouncedValue(globalFilter.trim(), SEARCH_DEBOUNCE_MS)
  const activeSort = sorting[0] ?? { id: "updated_at", desc: true }
  const { data, isFetching, isPlaceholderData } = useArtifactsQuery({
    limit: pagination.pageSize,
    offset: pagination.pageIndex * pagination.pageSize,
    ...(search ? { search } : {}),
    sortBy: activeSort.id as ArtifactSortField,
    sortDirection: activeSort.desc ? "desc" : "asc",
  })
  const isChangingView = isFetching || isPlaceholderData || search !== globalFilter.trim()

  const updateGlobalFilter = useCallback<OnChangeFn<string>>((updater) => {
    setGlobalFilter(updater)
    setPagination((current) => ({ ...current, pageIndex: 0 }))
  }, [])

  const updateSorting = useCallback<OnChangeFn<SortingState>>((updater) => {
    setSorting(updater)
    setPagination((current) => ({ ...current, pageIndex: 0 }))
  }, [])
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        description="Preview, revise, restore, and share durable work created by your agents."
        title="Artifacts"
      />
      <ArtifactsTable
        artifacts={data?.items ?? []}
        globalFilter={globalFilter}
        isChangingView={isChangingView}
        onGlobalFilterChange={updateGlobalFilter}
        onPaginationChange={setPagination}
        onSortingChange={updateSorting}
        pagination={pagination}
        sorting={sorting}
        total={data?.total ?? 0}
      />
    </div>
  )
}
