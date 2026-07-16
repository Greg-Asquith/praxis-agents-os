// apps/web/src/features/schedules/routes/schedules-route.tsx

import { Link } from "@tanstack/react-router"
import { PlusIcon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { useSchedulesQuery } from "@/features/schedules/api/list-schedules"
import { SchedulesTable } from "@/features/schedules/components/schedules-table"

export function SchedulesRoute() {
  const { data: schedulesData } = useSchedulesQuery({ includeInactive: true, limit: 100 })
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const hasSchedules = schedulesData.items.length > 0

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={
          hasSchedules ? (
            <Button render={<Link to="/schedules/new" />}>
              <PlusIcon data-icon="inline-start" />
              New schedule
            </Button>
          ) : null
        }
        description="Create and monitor unattended agent runs across this workspace."
        title="Schedules"
      />

      <SchedulesTable agents={agentsData.agents} schedules={schedulesData.items} />
    </div>
  )
}
