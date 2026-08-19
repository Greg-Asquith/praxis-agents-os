// apps/web/src/features/schedules/components/schedule-run-history.tsx

import { Link } from "@tanstack/react-router"
import { HistoryIcon, MessageSquareIcon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
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
import { useScheduleRunsQuery } from "@/features/schedules/api/list-schedule-runs"
import { ScheduleRunStatusBadge } from "@/features/schedules/components/schedule-status-badges"
import { hasActionableScheduleApproval } from "@/features/schedules/format"
import type { AgentScheduleRun } from "@/features/schedules/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime, pluralize, truncateText } from "@/lib/format"

const EMPTY_RUNS: AgentScheduleRun[] = []
const columnHelper = createAppColumnHelper<AgentScheduleRun>()

const columns = columnHelper.columns([
  columnHelper.accessor("scheduled_for", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => formatDateTime(getValue()),
    meta: { label: "Scheduled for" },
  }),
  columnHelper.accessor("status", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => (
      <ScheduleRunStatusBadge
        completionJson={row.original.completion_json}
        outcome={row.original.outcome}
        status={row.original.status}
      />
    ),
    meta: { label: "Status" },
  }),
  columnHelper.accessor("attempt_count", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => `${String(getValue())} ${pluralize(getValue(), "attempt")}`,
    meta: { label: "Attempts" },
  }),
  columnHelper.display({
    id: "error",
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => <RunError run={row.original} />,
    meta: { label: "Error" },
  }),
  columnHelper.display({
    id: "conversation",
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => <ConversationLink run={row.original} />,
    meta: { label: "Conversation", labelClassName: "sr-only" },
  }),
])

export function ScheduleRunHistory({
  enabled,
  scheduleId,
}: {
  enabled: boolean
  scheduleId: string
}) {
  const runsQuery = useScheduleRunsQuery(scheduleId, { limit: 100 }, enabled)
  const runs = runsQuery.data?.items ?? EMPTY_RUNS
  const table = useAppTable({ columns, data: runs })

  if (runsQuery.isPending) {
    return (
      <div className="text-muted-foreground rounded-md border p-6 text-sm">
        Loading run history...
      </div>
    )
  }

  if (runsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Run history unavailable</AlertTitle>
        <AlertDescription>{getErrorMessage(runsQuery.error)}</AlertDescription>
      </Alert>
    )
  }

  if (runs.length === 0) {
    return (
      <EmptyState
        description="Runs will appear here after the worker claims this schedule."
        icon={<HistoryIcon className="size-5" />}
        size="compact"
        title="No runs yet"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {runs.map((run) => (
          <ScheduleRunMobileRow key={run.id} run={run} />
        ))}
      </ResponsiveList>

      <table.AppTable>
        <ScheduleRunsDesktopTable />
      </table.AppTable>
    </div>
  )
}

function ScheduleRunsDesktopTable() {
  const table = useTableContext<AgentScheduleRun>()

  return (
    <div className="hidden md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <ScheduleRunHeaderCell />}
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
                  {() => <ScheduleRunBodyCell />}
                </table.AppCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function ScheduleRunHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function ScheduleRunBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell className={cell.column.id === "conversation" ? "text-right" : undefined}>
      <cell.FlexRender />
    </TableCell>
  )
}

function ScheduleRunMobileRow({ run }: { run: AgentScheduleRun }) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-medium">{formatDateTime(run.scheduled_for)}</p>
            <p className="text-muted-foreground truncate text-xs">
              {run.attempt_count} {pluralize(run.attempt_count, "attempt")}
            </p>
          </div>
          <ScheduleRunStatusBadge
            completionJson={run.completion_json}
            outcome={run.outcome}
            status={run.status}
          />
        </div>

        <dl className="grid gap-3">
          <ResponsiveListMeta label="Error">
            <RunError run={run} />
          </ResponsiveListMeta>
        </dl>

        <ConversationLink run={run} fullWidth />
      </div>
    </ResponsiveListItem>
  )
}

function RunError({ run }: { run: AgentScheduleRun }) {
  if (!run.last_error_code && !run.last_error_message) {
    return <span className="text-muted-foreground">None</span>
  }

  return (
    <span className="text-muted-foreground">
      {run.last_error_code ? `${run.last_error_code}: ` : null}
      {truncateText(run.last_error_message ?? "", 96)}
    </span>
  )
}

function ConversationLink({
  fullWidth = false,
  run,
}: {
  fullWidth?: boolean
  run: AgentScheduleRun
}) {
  if (!run.conversation_id) {
    return <span className="text-muted-foreground text-sm">No conversation</span>
  }

  const awaitingApproval = hasActionableScheduleApproval(run)

  return (
    <Button
      className={fullWidth ? "w-full" : undefined}
      size="sm"
      variant={awaitingApproval ? "default" : "outline"}
      render={
        <Link
          to="/conversations/$conversationId"
          params={{ conversationId: run.conversation_id }}
        />
      }
    >
      <MessageSquareIcon data-icon="inline-start" />
      {awaitingApproval ? "Review in Conversation" : "Open Conversation"}
    </Button>
  )
}
