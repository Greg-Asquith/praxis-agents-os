// apps/web/src/features/usage/components/usage-breakdown-table.tsx

import { useMemo } from "react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
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
import { formatShare, formatTokenCount, formatUsd, totalTokens } from "@/features/usage/format"
import type { UsageBreakdownRow } from "@/features/usage/types"

const columnHelper = createAppColumnHelper<UsageBreakdownRow>()

export function UsageBreakdownTable({ rows }: { rows: UsageBreakdownRow[] }) {
  const columns = useMemo(
    () =>
      columnHelper.columns([
        columnHelper.accessor("label", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => <span className="font-medium">{getValue()}</span>,
          enableSorting: true,
          meta: { label: "Name" },
        }),
        columnHelper.accessor("estimated_cost_usd", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => formatUsd(getValue()),
          enableSorting: true,
          sortFn: (rowA, rowB) =>
            Number(rowA.original.estimated_cost_usd ?? -1) -
            Number(rowB.original.estimated_cost_usd ?? -1),
          meta: { headClassName: "text-right", label: "Estimated cost" },
        }),
        columnHelper.accessor("token_share", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => formatShare(getValue()),
          enableSorting: true,
          sortFn: (rowA, rowB) =>
            Number(rowA.original.token_share) - Number(rowB.original.token_share),
          meta: { headClassName: "text-right", label: "Token share" },
        }),
        columnHelper.accessor((row) => totalTokens(row.tokens_by_class), {
          id: "tokens",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => formatTokenCount(getValue()),
          enableSorting: true,
          meta: { headClassName: "text-right", label: "Tokens" },
        }),
        columnHelper.accessor("requests", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => formatTokenCount(getValue()),
          enableSorting: true,
          meta: { headClassName: "text-right", label: "Requests" },
        }),
      ]),
    []
  )
  const table = useAppTable({ columns, data: rows, getRowId: (row) => row.key })

  return (
    <div>
      <ResponsiveList>
        {rows.map((row) => (
          <ResponsiveListItem key={row.key}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="font-medium">{row.label}</p>
                <p className="text-muted-foreground mt-1 text-xs">
                  {formatShare(row.token_share)} of tokens
                </p>
              </div>
              <p className="font-medium tabular-nums">{formatUsd(row.estimated_cost_usd)}</p>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-3">
              <ResponsiveListMeta label="Tokens">
                {formatTokenCount(totalTokens(row.tokens_by_class))}
              </ResponsiveListMeta>
              <ResponsiveListMeta label="Requests">
                {formatTokenCount(row.requests)}
              </ResponsiveListMeta>
            </dl>
          </ResponsiveListItem>
        ))}
      </ResponsiveList>
      <table.AppTable>
        <UsageDesktopTable />
      </table.AppTable>
    </div>
  )
}

function UsageDesktopTable() {
  const table = useTableContext<UsageBreakdownRow>()
  return (
    <div className="hidden md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <UsageHeaderCell />}
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
                  {() => <UsageBodyCell />}
                </table.AppCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function UsageHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function UsageBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell className={cell.column.id === "label" ? undefined : "text-right tabular-nums"}>
      <cell.FlexRender />
    </TableCell>
  )
}
