// apps/web/src/features/schedules/routes/schedule-detail-route.tsx

import { useState } from "react"
import { Link, useNavigate, useParams } from "@tanstack/react-router"
import {
  ArrowLeftIcon,
  CalendarClockIcon,
  HistoryIcon,
  PauseIcon,
  PlayIcon,
  RotateCcwIcon,
  Trash2Icon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { MetricCard } from "@/components/ui/metric-card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { useDeleteScheduleMutation } from "@/features/schedules/api/delete-schedule"
import { useEnableScheduleMutation } from "@/features/schedules/api/enable-schedule"
import { useScheduleQuery } from "@/features/schedules/api/get-schedule"
import { usePauseScheduleMutation } from "@/features/schedules/api/pause-schedule"
import { useRunScheduleNowMutation } from "@/features/schedules/api/run-schedule-now"
import { useUpdateScheduleMutation } from "@/features/schedules/api/update-schedule"
import { ScheduleForm } from "@/features/schedules/components/schedule-form"
import { ScheduleRunHistory } from "@/features/schedules/components/schedule-run-history"
import { ScheduleStatusBadges } from "@/features/schedules/components/schedule-status-badges"
import {
  formatScheduleCadence,
  formatScheduleNextRun,
  scheduleTitle,
} from "@/features/schedules/format"
import type { ScheduleUpdateRequest } from "@/features/schedules/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime } from "@/lib/format"

export function ScheduleDetailRoute() {
  const navigate = useNavigate()
  const params = useParams({ strict: false })
  const scheduleId = requireScheduleId(params.scheduleId)
  const { data: schedule } = useScheduleQuery(scheduleId)
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const updateScheduleMutation = useUpdateScheduleMutation()
  const deleteScheduleMutation = useDeleteScheduleMutation()
  const pauseScheduleMutation = usePauseScheduleMutation()
  const enableScheduleMutation = useEnableScheduleMutation()
  const runScheduleNowMutation = useRunScheduleNowMutation()
  const [actionError, setActionError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const agent = agentsData.agents.find((item) => item.id === schedule.agent_id) ?? null

  async function handleUpdateSchedule(payload: ScheduleUpdateRequest) {
    setActionError(null)
    setSaved(false)
    await updateScheduleMutation.mutateAsync({ scheduleId: schedule.id, payload })
    setSaved(true)
  }

  async function handlePauseOrEnable() {
    setActionError(null)
    setSaved(false)
    try {
      if (schedule.is_active) {
        await pauseScheduleMutation.mutateAsync(schedule.id)
      } else {
        await enableScheduleMutation.mutateAsync(schedule.id)
      }
    } catch (error) {
      setActionError(getErrorMessage(error))
    }
  }

  async function handleRunNow() {
    setActionError(null)
    setSaved(false)
    try {
      await runScheduleNowMutation.mutateAsync(schedule.id)
    } catch (error) {
      setActionError(getErrorMessage(error))
    }
  }

  async function handleDelete() {
    setActionError(null)
    setSaved(false)
    try {
      await deleteScheduleMutation.mutateAsync(schedule.id)
      await navigate({ to: "/schedules" })
    } catch (error) {
      setActionError(getErrorMessage(error))
      setDeleteDialogOpen(false)
    }
  }

  const togglePending = pauseScheduleMutation.isPending || enableScheduleMutation.isPending

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-col gap-3">
          <Button className="w-fit" size="sm" variant="outline" render={<Link to="/schedules" />}>
            <ArrowLeftIcon data-icon="inline-start" />
            Schedules
          </Button>
          <div className="flex flex-col gap-2">
            <ScheduleStatusBadges schedule={schedule} />
            <h1 className="font-heading text-2xl font-semibold tracking-normal">
              {scheduleTitle(schedule)}
            </h1>
            <p className="text-muted-foreground max-w-3xl text-sm">
              {agent?.name ?? "Unknown agent"} runs {formatScheduleCadence(schedule)}.
            </p>
          </div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row md:justify-end">
          <Button
            disabled={togglePending}
            onClick={() => {
              void handlePauseOrEnable()
            }}
            variant="outline"
          >
            {schedule.is_active ? (
              <>
                <PauseIcon data-icon="inline-start" />
                {pauseScheduleMutation.isPending ? "Pausing" : "Pause"}
              </>
            ) : (
              <>
                <PlayIcon data-icon="inline-start" />
                {enableScheduleMutation.isPending ? "Enabling" : "Enable"}
              </>
            )}
          </Button>
          <Button
            disabled={runScheduleNowMutation.isPending}
            onClick={() => {
              void handleRunNow()
            }}
            variant="outline"
          >
            <RotateCcwIcon data-icon="inline-start" />
            {runScheduleNowMutation.isPending ? "Starting" : "Run now"}
          </Button>
          <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
            <DialogTrigger render={<Button variant="destructive" />}>
              <Trash2Icon data-icon="inline-start" />
              Delete
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Delete schedule?</DialogTitle>
                <DialogDescription>
                  This removes the schedule from the workspace. Existing run history remains
                  available in the backend audit trail.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                <Button
                  disabled={deleteScheduleMutation.isPending}
                  onClick={() => {
                    void handleDelete()
                  }}
                  variant="destructive"
                >
                  <Trash2Icon data-icon="inline-start" />
                  {deleteScheduleMutation.isPending ? "Deleting" : "Delete schedule"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard
          description={formatScheduleCadence(schedule)}
          icon={<CalendarClockIcon className="size-4" />}
          title="Cadence"
        />
        <MetricCard
          description={formatScheduleNextRun(schedule)}
          icon={<RotateCcwIcon className="size-4" />}
          title="Next run"
        />
        <MetricCard
          description={formatDateTime(schedule.last_run_at)}
          icon={<HistoryIcon className="size-4" />}
          title="Last run"
        />
      </div>

      {actionError ? (
        <Alert variant="destructive">
          <AlertTitle>Schedule action failed</AlertTitle>
          <AlertDescription>{actionError}</AlertDescription>
        </Alert>
      ) : null}
      {saved ? (
        <Alert>
          <AlertTitle>Schedule updated</AlertTitle>
          <AlertDescription>Your changes have been saved.</AlertDescription>
        </Alert>
      ) : null}

      <Tabs defaultValue="settings">
        <TabsList variant="line">
          <TabsTrigger value="settings">Settings</TabsTrigger>
          <TabsTrigger value="history">Run history</TabsTrigger>
        </TabsList>
        <TabsContent value="settings">
          <div className="mx-auto w-full max-w-5xl">
            <ScheduleForm
              key={`${schedule.id}:${schedule.updated_at}`}
              agents={agentsData.agents}
              cancelLabel="Back to schedules"
              isSubmitting={updateScheduleMutation.isPending}
              mode="edit"
              onChange={() => {
                if (saved) {
                  setSaved(false)
                }
              }}
              onSubmit={handleUpdateSchedule}
              schedule={schedule}
            />
          </div>
        </TabsContent>
        <TabsContent value="history">
          <ScheduleRunHistory scheduleId={schedule.id} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function requireScheduleId(value: string | undefined) {
  if (!value) {
    throw new Error("Schedule route is missing a schedule id.")
  }

  return value
}
