// apps/web/src/features/schedules/components/schedules-table.tsx

import { useMemo, useRef, useState } from "react"
import { Link } from "@tanstack/react-router"
import { CalendarClockIcon, CircleAlertIcon, PencilIcon, PlusIcon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
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

const columnHelper = createAppColumnHelper<AgentSchedule>()

const columns = columnHelper.columns([
  columnHelper.display({
    id: "name",
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => <span className="truncate font-medium">{scheduleTitle(row.original)}</span>,
    meta: { label: "Name" },
  }),
  columnHelper.display({
    id: "cadence",
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => (
      <div className="flex min-w-0 flex-col gap-1">
        <ScheduleCadenceTooltip schedule={row.original} />
        {row.original.schedule_type !== "interval" ? (
          <span className="text-muted-foreground truncate text-xs">{row.original.timezone}</span>
        ) : null}
      </div>
    ),
    meta: { label: "Cadence" },
  }),
  columnHelper.accessor("health", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => <ScheduleHealthBadge health={getValue()} />,
    meta: { label: "Status" },
  }),
  columnHelper.accessor("is_active", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: () => null,
    meta: { label: "On" },
  }),
  columnHelper.accessor("next_run_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => formatScheduleNextRun(row.original),
    meta: { label: "Next run" },
  }),
  columnHelper.display({
    id: "last_run",
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => formatLatestRun(row.original),
    meta: { label: "Last run" },
  }),
  columnHelper.display({
    id: "actions",
    header: ({ header }) => <header.ColumnHeader />,
    cell: () => null,
    meta: { label: "Actions", labelClassName: "sr-only" },
  }),
])

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
  const agentNameById = useMemo(
    () => new Map(agents.map((agent) => [agent.id, agent.name])),
    [agents]
  )
  const table = useAppTable({ columns, data: schedules })

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
        <table.AppTable>
          <SchedulesDesktopTable
            agentNameById={agentNameById}
            onActiveChange={(schedule, isActive) => {
              void handleActiveChange(schedule, isActive)
            }}
            pendingScheduleIds={pendingScheduleIds}
          />
        </table.AppTable>
      </TooltipProvider>
    </div>
  )
}

function SchedulesDesktopTable({
  agentNameById,
  onActiveChange,
  pendingScheduleIds,
}: {
  agentNameById: ReadonlyMap<string, string>
  onActiveChange: (schedule: AgentSchedule, isActive: boolean) => void
  pendingScheduleIds: ReadonlySet<string>
}) {
  const table = useTableContext<AgentSchedule>()

  return (
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
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <ScheduleHeaderCell />}
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
                  {() => (
                    <ScheduleBodyCell
                      agentNameById={agentNameById}
                      onActiveChange={onActiveChange}
                      pendingScheduleIds={pendingScheduleIds}
                    />
                  )}
                </table.AppCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function ScheduleHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function ScheduleBodyCell({
  agentNameById,
  onActiveChange,
  pendingScheduleIds,
}: {
  agentNameById: ReadonlyMap<string, string>
  onActiveChange: (schedule: AgentSchedule, isActive: boolean) => void
  pendingScheduleIds: ReadonlySet<string>
}) {
  const cell = useCellContext()
  const schedule = useTableContext<AgentSchedule>().getRow(cell.row.id).original

  return (
    <TableCell
      className={
        cell.column.id === "actions"
          ? "text-right"
          : cell.column.id === "cadence"
            ? "overflow-hidden"
            : cell.column.id === "next_run_at" || cell.column.id === "last_run"
              ? "truncate"
              : undefined
      }
    >
      {cell.column.id === "name" ? (
        <div className="flex min-w-0 flex-col gap-1">
          <cell.FlexRender />
          <span className="text-muted-foreground truncate text-xs">
            {agentNameById.get(schedule.agent_id) ?? "Unknown agent"}
          </span>
        </div>
      ) : cell.column.id === "is_active" ? (
        <ScheduleActiveSwitch
          disabled={pendingScheduleIds.has(schedule.id)}
          onCheckedChange={(isActive) => {
            onActiveChange(schedule, isActive)
          }}
          schedule={schedule}
        />
      ) : cell.column.id === "actions" ? (
        <Button
          render={<Link params={{ scheduleId: schedule.id }} to="/schedules/$scheduleId" />}
          size="sm"
          variant="outline"
        >
          <PencilIcon data-icon="inline-start" />
          Edit
        </Button>
      ) : (
        <cell.FlexRender />
      )}
    </TableCell>
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
