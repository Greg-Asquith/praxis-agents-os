// apps/web/src/features/artifacts/components/artifacts-table.tsx

import { Link } from "@tanstack/react-router"
import type { OnChangeFn, PaginationState, SortingState } from "@tanstack/react-table"
import { FileCode2Icon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/ui/empty-state"
import {
  ResponsiveList,
  ResponsiveListItem,
  ResponsiveListMeta,
} from "@/components/ui/responsive-list"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { ArtifactSummary } from "@/features/artifacts/types"
import { artifactTypeLabel } from "@/features/artifacts/format"
import { formatCompactDate } from "@/lib/format"

const columnHelper = createAppColumnHelper<ArtifactSummary>()

const columns = columnHelper.columns([
  columnHelper.accessor("title", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => (
      <Link
        className="font-medium hover:underline"
        params={{ artifactId: row.original.id }}
        to="/artifacts/$artifactId"
      >
        {row.original.title}
      </Link>
    ),
    enableSorting: true,
    meta: { label: "Artifact" },
    sortDescFirst: false,
  }),
  columnHelper.accessor("artifact_type", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => <Badge variant="secondary">{artifactTypeLabel(getValue())}</Badge>,
    enableSorting: true,
    meta: { label: "Type" },
    sortDescFirst: false,
  }),
  columnHelper.accessor("version_count", {
    header: ({ header }) => <header.ColumnHeader />,
    enableSorting: true,
    meta: { label: "Versions" },
    sortDescFirst: true,
  }),
  columnHelper.accessor("updated_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => formatCompactDate(getValue()),
    enableSorting: true,
    meta: { label: "Updated" },
    sortDescFirst: true,
  }),
])

export function ArtifactsTable({
  artifacts,
  globalFilter,
  isChangingView,
  onGlobalFilterChange,
  onPaginationChange,
  onSortingChange,
  pagination,
  sorting,
  total,
}: {
  artifacts: ArtifactSummary[]
  globalFilter: string
  isChangingView: boolean
  onGlobalFilterChange: OnChangeFn<string>
  onPaginationChange: OnChangeFn<PaginationState>
  onSortingChange: OnChangeFn<SortingState>
  pagination: PaginationState
  sorting: SortingState
  total: number
}) {
  const table = useAppTable({
    columns,
    data: artifacts,
    enableSortingRemoval: false,
    manualFiltering: true,
    manualPagination: true,
    manualSorting: true,
    onGlobalFilterChange,
    onPaginationChange,
    onSortingChange,
    rowCount: total,
    state: { globalFilter, pagination, sorting },
  })

  if (total === 0 && !globalFilter.trim()) {
    return (
      <EmptyState
        description="Artifacts created by agents will appear here with their complete version history."
        icon={<FileCode2Icon className="size-5" />}
        title="No artifacts yet"
      />
    )
  }

  return (
    <table.AppTable>
      <div aria-busy={isChangingView} className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <table.Search
            ariaLabel="Search artifacts"
            className="max-w-sm"
            placeholder="Search titles and types…"
          />
          <table.SortMenu className="ml-auto md:hidden" disabled={isChangingView} />
        </div>
        {artifacts.length === 0 ? (
          <EmptyState
            description="Try a different title."
            icon={<FileCode2Icon className="size-5" />}
            size="compact"
            title="No matching artifacts"
          />
        ) : (
          <>
            <ArtifactsDesktopTable isChangingView={isChangingView} />
            <ResponsiveList className={isChangingView ? "opacity-60" : undefined}>
              {artifacts.map((artifact) => (
                <ResponsiveListItem key={artifact.id}>
                  <Link
                    className="font-medium hover:underline"
                    params={{ artifactId: artifact.id }}
                    to="/artifacts/$artifactId"
                  >
                    {artifact.title}
                  </Link>
                  <dl className="mt-3 grid grid-cols-3 gap-3">
                    <ResponsiveListMeta label="Type">
                      {artifactTypeLabel(artifact.artifact_type)}
                    </ResponsiveListMeta>
                    <ResponsiveListMeta label="Versions">
                      {artifact.version_count}
                    </ResponsiveListMeta>
                    <ResponsiveListMeta label="Updated">
                      {formatCompactDate(artifact.updated_at)}
                    </ResponsiveListMeta>
                  </dl>
                </ResponsiveListItem>
              ))}
            </ResponsiveList>
          </>
        )}
        <table.Pagination
          ariaLabel="Artifacts pagination"
          disabled={isChangingView}
          total={total}
        />
      </div>
    </table.AppTable>
  )
}

function ArtifactsDesktopTable({ isChangingView }: { isChangingView: boolean }) {
  const table = useTableContext<ArtifactSummary>()

  return (
    <div className="hidden overflow-hidden rounded-lg border md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <ArtifactHeaderCell />}
                </table.AppHeader>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody className={isChangingView ? "opacity-60" : undefined}>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <table.AppCell cell={cell} key={cell.id}>
                  {() => <ArtifactBodyCell />}
                </table.AppCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function ArtifactHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function ArtifactBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell>
      <cell.FlexRender />
    </TableCell>
  )
}
