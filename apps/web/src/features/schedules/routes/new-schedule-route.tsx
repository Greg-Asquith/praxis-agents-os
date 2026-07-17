// apps/web/src/features/schedules/routes/new-schedule-route.tsx

import { Link, useNavigate } from "@tanstack/react-router"
import { ArrowLeftIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { useCreateScheduleMutation } from "@/features/schedules/api/create-schedule"
import { ScheduleForm } from "@/features/schedules/components/schedule-form"
import type { ScheduleCreateRequest } from "@/features/schedules/types"

export function NewScheduleRoute() {
  const navigate = useNavigate()
  const { data: agentsData } = useAgentsQuery({ includeInactive: false, limit: 100 })
  const createScheduleMutation = useCreateScheduleMutation()

  async function handleCreateSchedule(payload: ScheduleCreateRequest) {
    await createScheduleMutation.mutateAsync(payload)
    await navigate({ to: "/schedules" })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex min-w-0 flex-col gap-3">
        <Button className="w-fit" size="sm" variant="outline" render={<Link to="/schedules" />}>
          <ArrowLeftIcon data-icon="inline-start" />
          Schedules
        </Button>
        <div className="flex flex-col gap-2">
          <h1 className="font-heading text-2xl font-semibold tracking-normal">New schedule</h1>
        </div>
      </div>

      <div className="mx-auto w-full max-w-5xl">
        <ScheduleForm
          agents={agentsData.agents}
          cancelLabel="Back to Schedules"
          isSubmitting={createScheduleMutation.isPending}
          mode="create"
          onSubmit={handleCreateSchedule}
        />
      </div>
    </div>
  )
}
