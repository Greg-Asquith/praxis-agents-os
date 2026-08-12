// apps/web/src/features/audit/components/audit-events-table.tsx

import { useMemo } from "react"
import type { OnChangeFn, PaginationState } from "@tanstack/react-table"
import { FileClockIcon } from "lucide-react"

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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
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
import type { AuditEvent } from "@/features/audit/types"
import { useToolLabels } from "@/features/tools/use-tool-labels"
import { formatDateTime, titleCaseToken, truncateText } from "@/lib/format"

const columnHelper = createAppColumnHelper<AuditEvent>()

function auditColumns(toolLabelFor: (toolName: string) => string) {
  return columnHelper.columns([
    columnHelper.accessor("occurred_at", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ getValue }) => formatDateTime(getValue()),
      meta: { label: "Occurred" },
    }),
    columnHelper.accessor("action", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <span>{titleCaseToken(row.original.action, row.original.action)}</span>
          <StatusBadge status={row.original.status} />
        </div>
      ),
      meta: { label: "Action" },
    }),
    columnHelper.accessor("resource_type", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ row }) => <ResourceName event={row.original} toolLabelFor={toolLabelFor} />,
      meta: { label: "Resource" },
    }),
    columnHelper.accessor("tool_name", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ getValue }) => {
        const toolName = getValue()
        return toolName ? (
          <ToolName value={toolLabelFor(toolName)} />
        ) : (
          <span className="text-muted-foreground">-</span>
        )
      },
      meta: { label: "Tool" },
    }),
    columnHelper.accessor("tool_provider", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ getValue }) => {
        const provider = getValue()
        return provider ? (
          titleCaseToken(provider, provider)
        ) : (
          <span className="text-muted-foreground">-</span>
        )
      },
      meta: { label: "Provider" },
    }),
    columnHelper.accessor("actor_display", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ row }) =>
        row.original.actor_display ?? titleCaseToken(row.original.actor_type, "Actor"),
      meta: { label: "Actor" },
    }),
    columnHelper.accessor("summary", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ getValue }) => (
        <span className="block max-w-72 truncate">{truncateText(getValue(), 120)}</span>
      ),
      meta: { label: "Summary" },
    }),
  ])
}

export function AuditEventsTable({
  events,
  isFetching,
  limit,
  offset,
  onPageChange,
  onSelectEvent,
  total,
}: {
  events: AuditEvent[]
  isFetching: boolean
  limit: number
  offset: number
  onPageChange: (offset: number) => void
  onSelectEvent: (eventId: string) => void
  total: number
}) {
  const toolLabelFor = useToolLabels()
  const columns = useMemo(() => auditColumns(toolLabelFor), [toolLabelFor])
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
        description="Audit events for this workspace will appear here after users or agents make changes."
        icon={<FileClockIcon className="size-5" />}
        size="compact"
        title={isFetching ? "Loading audit events" : "No audit events found"}
      />
    )
  }

  return (
    <table.AppTable>
      <div className="flex flex-col gap-3">
        <ResponsiveList>
          {events.map((event) => (
            <AuditEventMobileRow
              key={event.id}
              event={event}
              onSelectEvent={() => {
                onSelectEvent(event.detail_event_id)
              }}
              toolLabelFor={toolLabelFor}
            />
          ))}
        </ResponsiveList>

        <div className="hidden md:block">
          <TooltipProvider>
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <table.AppHeader header={header} key={header.id}>
                        {() => <AuditHeaderCell />}
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
                      onSelectEvent(row.original.detail_event_id)
                    }}
                    onKeyDown={(keyboardEvent) => {
                      if (keyboardEvent.key === "Enter" || keyboardEvent.key === " ") {
                        keyboardEvent.preventDefault()
                        onSelectEvent(row.original.detail_event_id)
                      }
                    }}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <table.AppCell cell={cell} key={cell.id}>
                        {() => <AuditBodyCell />}
                      </table.AppCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TooltipProvider>
        </div>

        <table.Pagination ariaLabel="Audit events pagination" total={total} />
      </div>
    </table.AppTable>
  )
}

function AuditHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function AuditBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell>
      <cell.FlexRender />
    </TableCell>
  )
}

function ToolName({ value }: { value: string }) {
  return (
    <Tooltip>
      <TooltipTrigger className="block max-w-48 truncate text-left" render={<span />}>
        {value}
      </TooltipTrigger>
      <TooltipContent className="max-w-sm wrap-break-word">{value}</TooltipContent>
    </Tooltip>
  )
}

function ResourceName({
  event,
  toolLabelFor,
}: {
  event: AuditEvent
  toolLabelFor: (toolName: string) => string
}) {
  const label = resourceLabel(event, toolLabelFor)
  const meta = resourceMeta(event)
  const fullValue = meta ? `${label}\n${meta}` : label

  return (
    <Tooltip>
      <TooltipTrigger className="flex max-w-64 min-w-0 flex-col gap-1 text-left" render={<div />}>
        <span className="truncate">{label}</span>
        {meta ? <span className="text-muted-foreground truncate text-xs">{meta}</span> : null}
      </TooltipTrigger>
      <TooltipContent className="max-w-sm wrap-break-word whitespace-pre-line">
        {fullValue}
      </TooltipContent>
    </Tooltip>
  )
}

function AuditEventMobileRow({
  event,
  onSelectEvent,
  toolLabelFor,
}: {
  event: AuditEvent
  onSelectEvent: () => void
  toolLabelFor: (toolName: string) => string
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-medium">{event.summary}</p>
            <p className="text-muted-foreground truncate text-xs">
              {formatDateTime(event.occurred_at)}
            </p>
          </div>
          <StatusBadge status={event.status} />
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Action">
            {titleCaseToken(event.action, event.action)}
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Resource">
            {resourceLabel(event, toolLabelFor)}
          </ResponsiveListMeta>
          {event.tool_name ? (
            <ResponsiveListMeta label="Tool">{toolLabelFor(event.tool_name)}</ResponsiveListMeta>
          ) : null}
          {event.tool_provider ? (
            <ResponsiveListMeta label="Provider">
              {titleCaseToken(event.tool_provider, event.tool_provider)}
            </ResponsiveListMeta>
          ) : null}
          <ResponsiveListMeta label="Actor">
            {event.actor_display ?? titleCaseToken(event.actor_type, "Actor")}
          </ResponsiveListMeta>
        </dl>

        <Button
          className="w-full"
          onClick={() => {
            onSelectEvent()
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

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge
      variant={
        status === "failure" || status === "denied"
          ? "destructive"
          : status === "unverified"
            ? "warning"
            : status === "success"
              ? "success"
              : "secondary"
      }
    >
      {titleCaseToken(status, status)}
    </Badge>
  )
}

function resourceLabel(event: AuditEvent, toolLabelFor: (toolName: string) => string) {
  if (event.resource_type === "tool_call" && event.tool_name) {
    return `${titleCaseToken(event.resource_type, event.resource_type)} ${toolLabelFor(
      event.tool_name
    )}`
  }
  return titleCaseToken(event.resource_type, event.resource_type)
}

function resourceMeta(event: AuditEvent) {
  if (event.resource_type === "tool_call") {
    return event.tool_name ?? event.resource_id
  }
  return event.resource_id
}
