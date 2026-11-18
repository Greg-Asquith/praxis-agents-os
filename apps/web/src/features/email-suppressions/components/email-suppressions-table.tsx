// apps/web/src/features/email-suppressions/components/email-suppressions-table.tsx

import { useMemo } from "react"
import { Trash2Icon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import { Button } from "@/components/ui/button"
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
import type { EmailSuppression } from "@/features/email-suppressions/types"
import { formatDateTime } from "@/lib/format"

const columnHelper = createAppColumnHelper<EmailSuppression>()

type EmailSuppressionsTableProps = {
  entries: EmailSuppression[]
  // Removal lets agents email someone again, so only owners and admins see it.
  onRemove: ((entry: EmailSuppression) => void) | null
}

export function EmailSuppressionsTable({ entries, onRemove }: EmailSuppressionsTableProps) {
  const columns = useMemo(
    () =>
      columnHelper.columns([
        columnHelper.accessor("email", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => <span className="font-medium break-all">{getValue()}</span>,
          meta: { label: "Email" },
        }),
        columnHelper.accessor("reason", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => <span className="line-clamp-2 min-w-48">{getValue()}</span>,
          meta: { label: "Reason" },
        }),
        columnHelper.display({
          id: "added_by",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => addedBy(row.original),
          meta: { label: "Added By" },
        }),
        columnHelper.accessor("created_at", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => formatDateTime(getValue()),
          meta: { label: "Added" },
        }),
        ...(onRemove
          ? [
              columnHelper.display({
                id: "actions",
                header: ({ header }) => <header.ColumnHeader />,
                cell: ({ row }) => (
                  <div className="flex justify-end">
                    <Button
                      aria-label={`Remove ${row.original.email}`}
                      onClick={() => {
                        onRemove(row.original)
                      }}
                      size="icon-sm"
                      type="button"
                      variant="ghost"
                    >
                      <Trash2Icon />
                    </Button>
                  </div>
                ),
                meta: { label: "Actions", labelClassName: "sr-only" },
              }),
            ]
          : []),
      ]),
    [onRemove]
  )
  const table = useAppTable({ columns, data: entries })

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {entries.map((entry) => (
          <ResponsiveListItem key={entry.id}>
            <div className="flex min-w-0 flex-col gap-3">
              <div className="flex min-w-0 items-start justify-between gap-3">
                <p className="min-w-0 font-medium break-all">{entry.email}</p>
                {onRemove ? (
                  <Button
                    aria-label={`Remove ${entry.email}`}
                    onClick={() => {
                      onRemove(entry)
                    }}
                    size="icon-sm"
                    type="button"
                    variant="ghost"
                  >
                    <Trash2Icon />
                  </Button>
                ) : null}
              </div>
              <p className="text-muted-foreground text-xs leading-5">{entry.reason}</p>
              <dl className="grid gap-3 sm:grid-cols-2">
                <ResponsiveListMeta label="Added By">{addedBy(entry)}</ResponsiveListMeta>
                <ResponsiveListMeta label="Added">
                  {formatDateTime(entry.created_at)}
                </ResponsiveListMeta>
              </dl>
            </div>
          </ResponsiveListItem>
        ))}
      </ResponsiveList>

      <table.AppTable>
        <DesktopTable />
      </table.AppTable>
    </div>
  )
}

function DesktopTable() {
  const table = useTableContext<EmailSuppression>()
  return (
    <div className="hidden md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <HeaderCell />}
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
                  {() => <BodyCell />}
                </table.AppCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function HeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function BodyCell() {
  const cell = useCellContext()
  return (
    <TableCell className={cell.column.id === "actions" ? "text-right" : undefined}>
      <cell.FlexRender />
    </TableCell>
  )
}

function addedBy(entry: EmailSuppression) {
  return entry.created_by_name ?? "Former member"
}
