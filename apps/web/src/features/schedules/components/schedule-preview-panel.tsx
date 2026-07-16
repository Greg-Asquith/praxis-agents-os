// apps/web/src/features/schedules/components/schedule-preview-panel.tsx

import { useMemo, useState } from "react"
import { ListChecksIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { usePreviewScheduleMutation } from "@/features/schedules/api/preview-schedule"
import {
  buildSchedulePreviewPayload,
  type ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTimeInTimeZone } from "@/lib/format"

export function SchedulePreviewPanel({ state }: { state: ScheduleFormState }) {
  const previewPayload = useMemo(() => buildSchedulePreviewPayload(state), [state])
  const previewPayloadKey = JSON.stringify(previewPayload)
  const [submittedPreviewPayloadKey, setSubmittedPreviewPayloadKey] = useState<string | null>(null)
  const { data: previewData, error, isPending, mutate } = usePreviewScheduleMutation()
  const hasCurrentPreview = submittedPreviewPayloadKey === previewPayloadKey
  const previewError = hasCurrentPreview && error ? getErrorMessage(error) : null
  const nextRuns = hasCurrentPreview ? (previewData?.next_runs ?? []) : []
  const previewTimezone = previewPayload?.timezone ?? state.timezone

  function handlePreview() {
    if (!previewPayload) {
      return
    }

    setSubmittedPreviewPayloadKey(previewPayloadKey)
    mutate(previewPayload)
  }

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
          disabled={!previewPayload || isPending}
          onClick={handlePreview}
          type="button"
          variant="outline"
        >
          <ListChecksIcon data-icon="inline-start" />
          {isPending ? "Previewing" : "Preview Next Runs"}
        </Button>
      </div>

      {previewError ? (
        <Alert variant="destructive">
          <AlertTitle>Preview unavailable</AlertTitle>
          <AlertDescription>{previewError}</AlertDescription>
        </Alert>
      ) : null}

      {!previewPayload && !previewError ? (
        <p className="bg-muted/30 text-muted-foreground rounded-lg p-4 text-sm">
          Complete the timing fields to preview upcoming runs.
        </p>
      ) : null}

      {previewPayload && !previewError && nextRuns.length === 0 && !isPending ? (
        <p className="bg-muted/30 text-muted-foreground rounded-lg p-4 text-sm">
          Preview upcoming runs before saving this schedule.
        </p>
      ) : null}

      {nextRuns.length > 0 ? (
        <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {nextRuns.map((runAt) => (
            <li key={runAt} className="rounded-md border p-3">
              <p className="text-muted-foreground text-xs font-medium">Next run</p>
              <p className="mt-1 text-sm font-medium">
                {formatDateTimeInTimeZone(runAt, previewTimezone)}
              </p>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  )
}
