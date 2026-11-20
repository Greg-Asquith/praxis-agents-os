// apps/web/src/features/memories/components/memories-table.tsx

import type { ReactNode } from "react"
import type { OnChangeFn, PaginationState } from "@tanstack/react-table"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import {
  paginationStateFromServer,
  paginationStateToServer,
} from "@/components/data-table/server-state"
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
import { memoryUsedByLabel } from "@/features/memories/components/memory-display"
import { MemoryOriginBadge } from "@/features/memories/components/memory-origin-badge"
import type { Memory } from "@/features/memories/types"
import { formatDateTime, relativeDateTime } from "@/lib/format"

const columnHelper = createAppColumnHelper<Memory>()

const columns = columnHelper.columns([
  columnHelper.accessor("title", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => getValue(),
    meta: { label: "Memory" },
  }),
  columnHelper.display({
    id: "origin",
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => <MemoryOriginBadge memory={row.original} />,
    meta: { label: "Came From" },
  }),
  columnHelper.display({
    id: "used_by",
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => memoryUsedByLabel(row.original),
    meta: { label: "Used By" },
  }),
  columnHelper.accessor("updated_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => (
      <span className="whitespace-nowrap" title={formatDateTime(getValue())}>
        {relativeDateTime(getValue())}
      </span>
    ),
    meta: { label: "Last Changed" },
  }),
])

export function MemoriesTable({
  empty,
  limit,
  memories,
  offset,
  onOpen,
  onPageChange,
  total,
}: {
  empty: ReactNode
  limit: number
  memories: Memory[]
  offset: number
  onOpen: (memoryId: string) => void
  onPageChange: (offset: number) => void
  total: number
}) {
  const pagination = paginationStateFromServer({ limit, offset }, total)
  const table = useAppTable({
    columns,
    data: memories,
    manualPagination: true,
    manualSorting: true,
    onPaginationChange: ((updater) => {
      const nextPagination = typeof updater === "function" ? updater(pagination) : updater
      onPageChange(paginationStateToServer(nextPagination).offset)
    }) satisfies OnChangeFn<PaginationState>,
    rowCount: total,
    state: { pagination },
  })

  if (memories.length === 0) {
    return empty
  }

  return (
    <table.AppTable>
      <div className="flex flex-col gap-3">
        <ResponsiveList>
          {memories.map((memory) => (
            <ResponsiveListItem key={memory.id}>
              <button
                className="flex w-full flex-col gap-3 text-left"
                onClick={() => {
                  onOpen(memory.id)
                }}
                type="button"
              >
                <MemorySummary memory={memory} />
                <dl className="grid grid-cols-2 gap-3">
                  <ResponsiveListMeta label="Came From">
                    <MemoryOriginBadge memory={memory} />
                  </ResponsiveListMeta>
                  <ResponsiveListMeta label="Used By">
                    {memoryUsedByLabel(memory)}
                  </ResponsiveListMeta>
                  <ResponsiveListMeta label="Last Changed">
                    {relativeDateTime(memory.updated_at)}
                  </ResponsiveListMeta>
                </dl>
              </button>
            </ResponsiveListItem>
          ))}
        </ResponsiveList>
        <div className="hidden md:block">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <table.AppHeader header={header} key={header.id}>
                      {() => <MemoryHeaderCell />}
                    </table.AppHeader>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <table.AppCell cell={cell} key={cell.id}>
                      {() => <MemoryBodyCell onOpen={onOpen} />}
                    </table.AppCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <table.Pagination ariaLabel="Memories pagination" total={total} />
      </div>
    </table.AppTable>
  )
}

function MemoryHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function MemoryBodyCell({ onOpen }: { onOpen: (memoryId: string) => void }) {
  const cell = useCellContext()
  const row = useTableContext<Memory>().getRow(cell.row.id)
  return (
    <TableCell>
      {cell.column.id === "title" ? (
        <button
          className="focus-visible:ring-ring/50 block w-full max-w-xl rounded-sm text-left outline-none focus-visible:ring-[3px]"
          onClick={() => {
            onOpen(row.original.id)
          }}
          type="button"
        >
          <MemorySummary memory={row.original} />
        </button>
      ) : (
        <cell.FlexRender />
      )}
    </TableCell>
  )
}

function MemorySummary({ memory }: { memory: Memory }) {
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="truncate font-medium hover:underline">{memory.title}</span>
      <span className="text-muted-foreground truncate text-xs">{memory.content_md}</span>
    </span>
  )
}
