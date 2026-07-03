// apps/web/src/features/schedules/components/schedule-run-history.tsx

import { Link } from "@tanstack/react-router"
import { HistoryIcon, MessageSquareIcon } from "lucide-react"

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
import type { AgentScheduleRun } from "@/features/schedules/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime, pluralize, truncateForPreview } from "@/lib/format"

export function ScheduleRunHistory({ scheduleId }: { scheduleId: string }) {
  const runsQuery = useScheduleRunsQuery(scheduleId, { limit: 100 })
  const runs = runsQuery.data?.items ?? []

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

      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Scheduled for</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Attempts</TableHead>
              <TableHead>Error</TableHead>
              <TableHead>
                <span className="sr-only">Conversation</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map((run) => (
              <TableRow key={run.id}>
                <TableCell>{formatDateTime(run.scheduled_for)}</TableCell>
                <TableCell>
                  <ScheduleRunStatusBadge status={run.status} />
                </TableCell>
                <TableCell>
                  {run.attempt_count} {pluralize(run.attempt_count, "attempt")}
                </TableCell>
                <TableCell>
                  <RunError run={run} />
                </TableCell>
                <TableCell className="text-right">
                  <ConversationLink run={run} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
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
          <ScheduleRunStatusBadge status={run.status} />
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
      {truncateForPreview(run.last_error_message ?? "", 96)}
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

  const awaitingApproval = run.status === "awaiting_approval"

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
      {awaitingApproval ? "Review in conversation" : "Open conversation"}
    </Button>
  )
}
