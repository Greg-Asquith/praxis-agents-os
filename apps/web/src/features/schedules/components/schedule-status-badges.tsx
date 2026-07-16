// apps/web/src/features/schedules/components/schedule-status-badges.tsx

import { ShieldAlertIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { AgentSchedule, ScheduleHealth, ScheduleRunStatus } from "@/features/schedules/types"
import { titleCaseToken } from "@/lib/format"

export function ScheduleStatusBadges({ schedule }: { schedule: AgentSchedule }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant={schedule.is_active ? "success" : "outline"}>
        {schedule.is_active ? "Active" : "Paused"}
      </Badge>
      <ScheduleHealthBadge health={schedule.health} />
    </div>
  )
}

function ScheduleHealthBadge({ health }: { health: ScheduleHealth }) {
  if (health === "needs_attention") {
    return <Badge variant="destructive">Needs attention</Badge>
  }

  if (health === "retrying") {
    return <Badge variant="warning">Retrying</Badge>
  }

  if (health === "cancelled") {
    return <Badge variant="destructive">Cancelled</Badge>
  }

  return <Badge variant="outline">Healthy</Badge>
}

export function ScheduleRunStatusBadge({ status }: { status: ScheduleRunStatus }) {
  if (status === "awaiting_approval") {
    return (
      <Badge variant="warning">
        <ShieldAlertIcon data-icon="inline-start" />
        Awaiting approval
      </Badge>
    )
  }

  if (status === "terminal_failed" || status === "cancelled") {
    return <Badge variant="destructive">{scheduleRunStatusLabel(status)}</Badge>
  }

  if (status === "retryable_failed") {
    return <Badge variant="warning">{scheduleRunStatusLabel(status)}</Badge>
  }

  if (status === "completed") {
    return <Badge variant="success">{scheduleRunStatusLabel(status)}</Badge>
  }

  return <Badge variant="secondary">{scheduleRunStatusLabel(status)}</Badge>
}

function scheduleRunStatusLabel(status: ScheduleRunStatus) {
  return titleCaseToken(status, "Run")
}
