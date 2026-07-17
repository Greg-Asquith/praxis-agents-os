// apps/web/src/features/schedules/components/schedules-table.tsx

import { useRef, useState } from "react"
import { Link } from "@tanstack/react-router"
import { CalendarClockIcon, CircleAlertIcon, PencilIcon, PlusIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
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
import { Switch } from "@/components/ui/switch"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import type { Agent } from "@/features/agents/types"
import { useEnableScheduleMutation } from "@/features/schedules/api/enable-schedule"
import { usePauseScheduleMutation } from "@/features/schedules/api/pause-schedule"
import { ScheduleHealthBadge } from "@/features/schedules/components/schedule-status-badges"
import {
  formatScheduleCadence,
  formatScheduleNextRun,
  scheduleTitle,
} from "@/features/schedules/format"
import type { AgentSchedule } from "@/features/schedules/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime, titleCaseToken } from "@/lib/format"

export function SchedulesTable({
  agents,
  schedules,
}: {
  agents: Agent[]
  schedules: AgentSchedule[]
}) {
  const enableScheduleMutation = useEnableScheduleMutation()
  const pauseScheduleMutation = usePauseScheduleMutation()
  const pendingScheduleIdsRef = useRef(new Set<string>())
  const [pendingScheduleIds, setPendingScheduleIds] = useState<ReadonlySet<string>>(() => new Set())
  const [actionError, setActionError] = useState<string | null>(null)
  const agentNameById = new Map(agents.map((agent) => [agent.id, agent.name]))

  async function handleActiveChange(schedule: AgentSchedule, isActive: boolean) {
    if (isActive === schedule.is_active || pendingScheduleIdsRef.current.has(schedule.id)) {
      return
    }

    setActionError(null)
    pendingScheduleIdsRef.current.add(schedule.id)
    setPendingScheduleIds(new Set(pendingScheduleIdsRef.current))

    try {
      if (isActive) {
        await enableScheduleMutation.mutateAsync(schedule.id)
      } else {
        await pauseScheduleMutation.mutateAsync(schedule.id)
      }
    } catch (error) {
      setActionError(
        `Could not turn ${scheduleTitle(schedule)} ${isActive ? "on" : "off"}. ${getErrorMessage(error)}`
      )
    } finally {
      pendingScheduleIdsRef.current.delete(schedule.id)
      setPendingScheduleIds(new Set(pendingScheduleIdsRef.current))
    }
  }

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
      {actionError ? (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Schedule not updated</AlertTitle>
          <AlertDescription>{actionError}</AlertDescription>
        </Alert>
      ) : null}

      <ResponsiveList>
        {schedules.map((schedule) => (
          <ScheduleMobileRow
            key={schedule.id}
            agentName={agentNameById.get(schedule.agent_id) ?? "Unknown agent"}
            isToggleDisabled={pendingScheduleIds.has(schedule.id)}
            onActiveChange={(isActive) => {
              void handleActiveChange(schedule, isActive)
            }}
            schedule={schedule}
          />
        ))}
      </ResponsiveList>

      <TooltipProvider>
        <div className="hidden md:block">
          <Table className="min-w-5xl table-fixed">
            <colgroup>
              <col className="w-56" />
              <col className="w-44" />
              <col className="w-32" />
              <col className="w-16" />
              <col className="w-40" />
              <col className="w-52" />
              <col className="w-24" />
            </colgroup>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Cadence</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>On</TableHead>
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
                    <div className="flex min-w-0 flex-col gap-1">
                      <span className="truncate font-medium">{scheduleTitle(schedule)}</span>
                      <span className="text-muted-foreground truncate text-xs">
                        {agentNameById.get(schedule.agent_id) ?? "Unknown agent"}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="overflow-hidden">
                    <div className="flex min-w-0 flex-col gap-1">
                      <ScheduleCadenceTooltip schedule={schedule} />
                      {schedule.schedule_type !== "interval" ? (
                        <span className="text-muted-foreground truncate text-xs">
                          {schedule.timezone}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <ScheduleHealthBadge health={schedule.health} />
                  </TableCell>
                  <TableCell>
                    <ScheduleActiveSwitch
                      disabled={pendingScheduleIds.has(schedule.id)}
                      onCheckedChange={(isActive) => {
                        void handleActiveChange(schedule, isActive)
                      }}
                      schedule={schedule}
                    />
                  </TableCell>
                  <TableCell className="truncate">{formatScheduleNextRun(schedule)}</TableCell>
                  <TableCell className="truncate">{formatLatestRun(schedule)}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="outline"
                      render={
                        <Link to="/schedules/$scheduleId" params={{ scheduleId: schedule.id }} />
                      }
                    >
                      <PencilIcon data-icon="inline-start" />
                      Edit
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </TooltipProvider>
    </div>
  )
}

function ScheduleMobileRow({
  agentName,
  isToggleDisabled,
  onActiveChange,
  schedule,
}: {
  agentName: string
  isToggleDisabled: boolean
  onActiveChange: (isActive: boolean) => void
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
          <ScheduleHealthBadge health={schedule.health} />
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

        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-medium">Schedule</span>
            <span className="text-muted-foreground text-xs">
              {schedule.is_active ? "On" : "Off"}
            </span>
          </div>
          <ScheduleActiveSwitch
            disabled={isToggleDisabled}
            onCheckedChange={onActiveChange}
            schedule={schedule}
          />
        </div>

        <Button
          className="w-full"
          variant="outline"
          render={<Link to="/schedules/$scheduleId" params={{ scheduleId: schedule.id }} />}
        >
          <PencilIcon data-icon="inline-start" />
          Edit
        </Button>
      </div>
    </ResponsiveListItem>
  )
}

function ScheduleCadenceTooltip({ schedule }: { schedule: AgentSchedule }) {
  const cadence = formatScheduleCadence(schedule)

  return (
    <Tooltip>
      <TooltipTrigger className="block w-full truncate text-left">{cadence}</TooltipTrigger>
      <TooltipContent>{cadence}</TooltipContent>
    </Tooltip>
  )
}

function ScheduleActiveSwitch({
  disabled,
  onCheckedChange,
  schedule,
}: {
  disabled: boolean
  onCheckedChange: (isActive: boolean) => void
  schedule: AgentSchedule
}) {
  return (
    <Switch
      aria-label={`${schedule.is_active ? "Turn off" : "Turn on"} ${scheduleTitle(schedule)}`}
      checked={schedule.is_active}
      disabled={disabled}
      onCheckedChange={onCheckedChange}
    />
  )
}

function formatLatestRun(schedule: AgentSchedule) {
  if (!schedule.latest_run) {
    return "Never"
  }

  return `${formatDateTime(schedule.latest_run.scheduled_for)} · ${titleCaseToken(
    schedule.latest_run.status.replace(/_/g, " "),
    schedule.latest_run.status.replace(/_/g, " ")
  )}`
}
