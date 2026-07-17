// apps/web/src/features/schedules/components/schedule-preview-panel.tsx

import { ListChecksIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import type {
  SchedulePreviewStatus,
  SchedulePreviewView,
} from "@/features/schedules/components/use-schedule-preview"
import { formatDateTimeInTimeZone } from "@/lib/format"

export function SchedulePreviewPanel({ preview }: { preview: SchedulePreviewView }) {
  return (
    <div className="bg-card flex flex-col gap-4 rounded-md border p-4">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="font-heading flex items-center gap-2 text-lg font-semibold tracking-normal">
            <ListChecksIcon className="size-4" />
            Fire-time preview
          </h2>
          <p className="text-muted-foreground text-sm">
            The next five times this schedule would fire with the current timing settings.
          </p>
        </div>
        <Button
          className="w-full sm:w-auto"
          disabled={!preview.canPreview || preview.isRequestPending}
          onClick={preview.requestPreview}
          type="button"
          variant="outline"
        >
          <ListChecksIcon data-icon="inline-start" />
          {preview.isRequestPending ? "Previewing" : "Preview Next Runs"}
        </Button>
      </div>

      <SchedulePreviewResult preview={preview} />
    </div>
  )
}

export function SchedulePreviewResult({ preview }: { preview: SchedulePreviewView }) {
  if (preview.status === "error") {
    return (
      <Alert variant="destructive">
        <AlertTitle>Preview unavailable</AlertTitle>
        <AlertDescription>{preview.error}</AlertDescription>
      </Alert>
    )
  }

  if (preview.status === "success" && preview.nextRuns.length > 0) {
    return (
      <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {preview.nextRuns.map((runAt) => (
          <li key={runAt} className="rounded-md border p-3">
            <p className="text-muted-foreground text-xs font-medium">Next run</p>
            <p className="mt-1 text-sm font-medium">
              {formatDateTimeInTimeZone(runAt, preview.timezone)}
            </p>
          </li>
        ))}
      </ol>
    )
  }

  return (
    <p className="bg-muted/30 text-muted-foreground rounded-lg p-4 text-sm">
      {previewMessage(preview.status)}
    </p>
  )
}

function previewMessage(status: Exclude<SchedulePreviewStatus, "error">) {
  switch (status) {
    case "incomplete":
      return "Complete the timing fields to preview upcoming runs."
    case "pending":
      return "Finding the next run times."
    case "stale":
      return "Timing changed since the last preview. Preview again to refresh the run times."
    case "success":
      return "The preview returned no upcoming runs."
    case "idle":
      return "Preview upcoming runs before saving this schedule."
  }
}
