// apps/web/src/features/memories/components/memories-table.tsx

import { BrainIcon } from "lucide-react"
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
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import {
  formatMemoryConfidence,
  memoryScopeLabel,
} from "@/features/memories/components/memory-display"
import type { Memory } from "@/features/memories/types"
import { relativeDateTime, titleCaseToken } from "@/lib/format"

const columnHelper = createAppColumnHelper<Memory>()

const columns = columnHelper.columns([
  columnHelper.accessor("title", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => getValue(),
    meta: { label: "Title" },
  }),
  columnHelper.accessor("scope", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => <ScopeBadge scope={getValue()} />,
    meta: { label: "Scope" },
  }),
  columnHelper.accessor("kind", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => <KindBadge kind={getValue()} />,
    meta: { label: "Kind" },
  }),
  columnHelper.accessor("memory_type", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => titleCaseToken(getValue(), "Memory"),
    meta: { label: "Type" },
  }),
  columnHelper.accessor("agent_name", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => getValue() ?? "—",
    meta: { label: "Agent" },
  }),
  columnHelper.accessor("effective_confidence", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => formatMemoryConfidence(getValue()),
    meta: { label: "Confidence" },
  }),
  columnHelper.accessor("updated_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => <span title={getValue()}>{relativeDateTime(getValue())}</span>,
    meta: { label: "Updated" },
  }),
])

export function MemoriesTable({
  limit,
  memories,
  offset,
  onOpen,
  onPageChange,
  total,
}: {
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
    return (
      <EmptyState
        description="Agents save durable details here as they work. Notes stay searchable, while core memories are available on every relevant run."
        icon={<BrainIcon className="size-5" />}
        size="compact"
        title="No memories match these filters"
      />
    )
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
                <div className="flex items-start justify-between gap-3">
                  <span className="font-medium">{memory.title}</span>
                  <KindBadge kind={memory.kind} />
                </div>
                <dl className="grid grid-cols-2 gap-3">
                  <ResponsiveListMeta label="Scope">{memoryScopeLabel(memory)}</ResponsiveListMeta>
                  <ResponsiveListMeta label="Type">
                    {titleCaseToken(memory.memory_type, "Memory")}
                  </ResponsiveListMeta>
                  <ResponsiveListMeta label="Confidence">
                    {formatMemoryConfidence(memory.effective_confidence)}
                  </ResponsiveListMeta>
                  <ResponsiveListMeta label="Updated">
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
        <Button
          className="h-auto max-w-sm justify-start truncate p-0 font-medium"
          onClick={() => {
            onOpen(row.original.id)
          }}
          type="button"
          variant="link"
        >
          <cell.FlexRender />
        </Button>
      ) : (
        <cell.FlexRender />
      )}
    </TableCell>
  )
}

function KindBadge({ kind }: { kind: Memory["kind"] }) {
  return (
    <Badge variant={kind === "core" ? "warning" : "secondary"}>
      {titleCaseToken(kind, "Memory")}
    </Badge>
  )
}

function ScopeBadge({ scope }: { scope: Memory["scope"] }) {
  return (
    <Badge variant="outline">
      {scope === "user" ? "Personal" : titleCaseToken(scope, "Scope")}
    </Badge>
  )
}
