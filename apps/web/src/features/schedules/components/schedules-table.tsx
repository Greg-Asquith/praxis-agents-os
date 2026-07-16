// apps/web/src/features/schedules/components/schedules-table.tsx

import { Link } from "@tanstack/react-router"
import { CalendarClockIcon, PlusIcon, Settings2Icon } from "lucide-react"

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
import type { Agent } from "@/features/agents/types"
import { ScheduleStatusBadges } from "@/features/schedules/components/schedule-status-badges"
import {
  formatScheduleCadence,
  formatScheduleNextRun,
  scheduleTitle,
} from "@/features/schedules/format"
import type { AgentSchedule } from "@/features/schedules/types"
import { formatDateTime } from "@/lib/format"

export function SchedulesTable({
  agents,
  schedules,
}: {
  agents: Agent[]
  schedules: AgentSchedule[]
}) {
  const agentNameById = new Map(agents.map((agent) => [agent.id, agent.name]))

  if (schedules.length === 0) {
    return (
      <EmptyState
        action={
          <Button render={<Link to="/schedules/new" />}>
            <PlusIcon data-icon="inline-start" />
            New Schedule
          </Button>
        }
        description="Create a schedule to run an agent on a cron, interval, or one-time cadence."
        icon={<CalendarClockIcon className="size-5" />}
        size="compact"
        title="No schedules yet"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {schedules.map((schedule) => (
          <ScheduleMobileRow
            key={schedule.id}
            agentName={agentNameById.get(schedule.agent_id) ?? "Unknown agent"}
            schedule={schedule}
          />
        ))}
      </ResponsiveList>

      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Cadence</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Next run</TableHead>
              <TableHead>Last run</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {schedules.map((schedule) => (
              <TableRow key={schedule.id}>
                <TableCell>
                  <div className="flex min-w-56 flex-col gap-1">
                    <span className="font-medium">{scheduleTitle(schedule)}</span>
                    <span className="text-muted-foreground text-xs">
                      {agentNameById.get(schedule.agent_id) ?? "Unknown agent"}
                    </span>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-col gap-1">
                    <span>{formatScheduleCadence(schedule)}</span>
                    {schedule.schedule_type !== "interval" ? (
                      <span className="text-muted-foreground text-xs">{schedule.timezone}</span>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell>
                  <ScheduleStatusBadges schedule={schedule} />
                </TableCell>
                <TableCell>{formatScheduleNextRun(schedule)}</TableCell>
                <TableCell>{formatLatestRun(schedule)}</TableCell>
                <TableCell className="text-right">
                  <Button
                    size="sm"
                    variant="outline"
                    render={
                      <Link to="/schedules/$scheduleId" params={{ scheduleId: schedule.id }} />
                    }
                  >
                    <Settings2Icon data-icon="inline-start" />
                    Configure
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function ScheduleMobileRow({
  agentName,
  schedule,
}: {
  agentName: string
  schedule: AgentSchedule
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-medium">{scheduleTitle(schedule)}</p>
            <p className="text-muted-foreground truncate text-xs">{agentName}</p>
          </div>
          <ScheduleStatusBadges schedule={schedule} />
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Cadence">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="outline">{formatScheduleCadence(schedule)}</Badge>
              {schedule.schedule_type !== "interval" ? (
                <Badge variant="ghost">{schedule.timezone}</Badge>
              ) : null}
            </div>
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Next run">
            {formatScheduleNextRun(schedule)}
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Last run">{formatLatestRun(schedule)}</ResponsiveListMeta>
        </dl>

        <Button
          className="w-full"
          variant="outline"
          render={<Link to="/schedules/$scheduleId" params={{ scheduleId: schedule.id }} />}
        >
          <Settings2Icon data-icon="inline-start" />
          Configure
        </Button>
      </div>
    </ResponsiveListItem>
  )
}

function formatLatestRun(schedule: AgentSchedule) {
  if (!schedule.latest_run) {
    return "Never"
  }

  return `${formatDateTime(schedule.latest_run.scheduled_for)} · ${schedule.latest_run.status.replace(
    /_/g,
    " "
  )}`
}
