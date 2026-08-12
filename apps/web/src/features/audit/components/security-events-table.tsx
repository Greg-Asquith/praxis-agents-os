// apps/web/src/features/audit/components/security-events-table.tsx

import { ShieldAlertIcon } from "lucide-react"
import type { OnChangeFn, PaginationState } from "@tanstack/react-table"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
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
import type { SecurityEvent } from "@/features/audit/types"
import { formatDateTime, titleCaseToken } from "@/lib/format"

const columnHelper = createAppColumnHelper<SecurityEvent>()

const columns = columnHelper.columns([
  columnHelper.accessor("occurred_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => formatDateTime(getValue()),
    meta: { label: "Occurred" },
  }),
  columnHelper.accessor("event_type", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => (
      <Badge variant="outline">{titleCaseToken(getValue(), getValue())}</Badge>
    ),
    meta: { label: "Event" },
  }),
  columnHelper.accessor("user_email", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => getValue() ?? "None",
    meta: { label: "User" },
  }),
  columnHelper.accessor("ip_address", {
    header: ({ header }) => <header.ColumnHeader />,
    meta: { label: "IP address" },
  }),
  columnHelper.accessor("endpoint", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => <span className="block max-w-72 truncate">{getValue() ?? "None"}</span>,
    meta: { label: "Endpoint" },
  }),
])

export function SecurityEventsTable({
  events,
  isFetching,
  limit,
  offset,
  onPageChange,
  onSelectEvent,
  total,
}: {
  events: SecurityEvent[]
  isFetching: boolean
  limit: number
  offset: number
  onPageChange: (offset: number) => void
  onSelectEvent: (eventId: string) => void
  total: number
}) {
  const pagination = paginationStateFromServer({ limit, offset }, total)
  const table = useAppTable({
    columns,
    data: events,
    manualPagination: true,
    manualSorting: true,
    onPaginationChange: ((updater) => {
      const nextPagination = typeof updater === "function" ? updater(pagination) : updater
      onPageChange(paginationStateToServer(nextPagination).offset)
    }) satisfies OnChangeFn<PaginationState>,
    rowCount: total,
    state: { pagination },
  })

  if (events.length === 0) {
    return (
      <EmptyState
        description="Global security events will appear here after authentication, rate-limit, or invitation activity."
        icon={<ShieldAlertIcon className="size-5" />}
        size="compact"
        title={isFetching ? "Loading security events" : "No security events found"}
      />
    )
  }

  return (
    <table.AppTable>
      <div className="flex flex-col gap-3">
        <ResponsiveList>
          {events.map((event) => (
            <SecurityEventMobileRow key={event.id} event={event} onSelectEvent={onSelectEvent} />
          ))}
        </ResponsiveList>

        <div className="hidden md:block">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <table.AppHeader header={header} key={header.id}>
                      {() => <SecurityHeaderCell />}
                    </table.AppHeader>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className="cursor-pointer"
                  tabIndex={0}
                  onClick={() => {
                    onSelectEvent(row.original.id)
                  }}
                  onKeyDown={(keyboardEvent) => {
                    if (keyboardEvent.key === "Enter" || keyboardEvent.key === " ") {
                      keyboardEvent.preventDefault()
                      onSelectEvent(row.original.id)
                    }
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <table.AppCell cell={cell} key={cell.id}>
                      {() => <SecurityBodyCell />}
                    </table.AppCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <table.Pagination ariaLabel="Security events pagination" total={total} />
      </div>
    </table.AppTable>
  )
}

function SecurityHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function SecurityBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell>
      <cell.FlexRender />
    </TableCell>
  )
}

function SecurityEventMobileRow({
  event,
  onSelectEvent,
}: {
  event: SecurityEvent
  onSelectEvent: (eventId: string) => void
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">
            {titleCaseToken(event.event_type, event.event_type)}
          </p>
          <p className="text-muted-foreground truncate text-xs">
            {formatDateTime(event.occurred_at)}
          </p>
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="User">{event.user_email ?? "None"}</ResponsiveListMeta>
          <ResponsiveListMeta label="IP address">{event.ip_address}</ResponsiveListMeta>
          <ResponsiveListMeta label="Endpoint">{event.endpoint ?? "None"}</ResponsiveListMeta>
        </dl>

        <Button
          className="w-full"
          onClick={() => {
            onSelectEvent(event.id)
          }}
          type="button"
          variant="outline"
        >
          View Details
        </Button>
      </div>
    </ResponsiveListItem>
  )
}
