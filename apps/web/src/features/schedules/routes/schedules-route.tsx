// apps/web/src/features/schedules/routes/schedules-route.tsx

import { useMemo } from "react"
import { Link } from "@tanstack/react-router"
import { AlertTriangleIcon, CalendarClockIcon, PlusIcon, ShieldAlertIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { MetricCard } from "@/components/ui/metric-card"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { useSchedulesQuery } from "@/features/schedules/api/list-schedules"
import { SchedulesTable } from "@/features/schedules/components/schedules-table"
import type { AgentSchedule } from "@/features/schedules/types"
import { pluralize } from "@/lib/format"

export function SchedulesRoute() {
  const { data: schedulesData } = useSchedulesQuery({ includeInactive: true, limit: 100 })
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const metrics = useMemo(() => buildScheduleMetrics(schedulesData.items), [schedulesData.items])
  const hasSchedules = schedulesData.items.length > 0

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-col gap-2">
          <p className="text-muted-foreground text-sm font-medium">Automation</p>
          <h1 className="font-heading text-2xl font-semibold tracking-normal">Schedules</h1>
        </div>
        {hasSchedules ? (
          <Button render={<Link to="/schedules/new" />}>
            <PlusIcon data-icon="inline-start" />
            New schedule
          </Button>
        ) : null}
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard
          description={`${String(metrics.active)} active ${pluralize(metrics.active, "schedule")}`}
          icon={<CalendarClockIcon className="size-4" />}
          title="Active"
        />
        <MetricCard
          description={`${String(metrics.needsAttention)} ${pluralize(
            metrics.needsAttention,
            "schedule"
          )} with terminal failures`}
          icon={<AlertTriangleIcon className="size-4" />}
          title="Needs attention"
        />
        <MetricCard
          description={`${String(metrics.awaitingApproval)} ${pluralize(
            metrics.awaitingApproval,
            "run"
          )} paused for review`}
          icon={<ShieldAlertIcon className="size-4" />}
          title="Awaiting approval"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Workspace schedules</CardTitle>
          <CardDescription>
            Create and monitor unattended agent runs across this workspace.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SchedulesTable agents={agentsData.agents} schedules={schedulesData.items} />
        </CardContent>
      </Card>
    </div>
  )
}

function buildScheduleMetrics(schedules: AgentSchedule[]) {
  return schedules.reduce(
    (metrics, schedule) => {
      if (schedule.is_active) {
        metrics.active += 1
      }

      if (schedule.health === "needs_attention") {
        metrics.needsAttention += 1
      }

      if (schedule.latest_run?.status === "awaiting_approval") {
        metrics.awaitingApproval += 1
      }

      return metrics
    },
    { active: 0, awaitingApproval: 0, needsAttention: 0 }
  )
}
