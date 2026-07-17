// apps/web/src/features/schedules/components/use-schedule-preview.ts

import { useMemo, useState } from "react"

import { usePreviewScheduleMutation } from "@/features/schedules/api/preview-schedule"
import {
  buildSchedulePreviewPayload,
  type ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"
import { getErrorMessage } from "@/lib/api/errors"

export type SchedulePreviewStatus =
  "error" | "idle" | "incomplete" | "pending" | "stale" | "success"

export type SchedulePreviewView = {
  canPreview: boolean
  error: string | null
  isRequestPending: boolean
  nextRuns: string[]
  requestPreview: () => void
  status: SchedulePreviewStatus
  timezone: string
}

export function useSchedulePreview(state: ScheduleFormState): SchedulePreviewView {
  const previewPayload = useMemo(() => buildSchedulePreviewPayload(state), [state])
  const previewPayloadKey = JSON.stringify(previewPayload)
  const [submittedPreviewPayloadKey, setSubmittedPreviewPayloadKey] = useState<string | null>(null)
  const { data, error, isPending, mutate } = usePreviewScheduleMutation()
  const hasCurrentPreview = submittedPreviewPayloadKey === previewPayloadKey
  const status = previewStatus({
    hasCurrentPreview,
    hasSubmittedPreview: submittedPreviewPayloadKey !== null,
    isPending,
    previewError: error,
    previewPayloadExists: previewPayload !== null,
    previewResultExists: data !== undefined,
  })

  function requestPreview() {
    if (!previewPayload) {
      return
    }
    setSubmittedPreviewPayloadKey(previewPayloadKey)
    mutate(previewPayload)
  }

  return {
    canPreview: previewPayload !== null,
    error: status === "error" && error ? getErrorMessage(error) : null,
    isRequestPending: isPending,
    nextRuns: status === "success" ? (data?.next_runs ?? []) : [],
    requestPreview,
    status,
    timezone: previewPayload?.timezone ?? state.timezone,
  }
}

function previewStatus({
  hasCurrentPreview,
  hasSubmittedPreview,
  isPending,
  previewError,
  previewPayloadExists,
  previewResultExists,
}: {
  hasCurrentPreview: boolean
  hasSubmittedPreview: boolean
  isPending: boolean
  previewError: Error | null
  previewPayloadExists: boolean
  previewResultExists: boolean
}): SchedulePreviewStatus {
  if (!previewPayloadExists) {
    return "incomplete"
  }
  if (!hasCurrentPreview) {
    return hasSubmittedPreview ? "stale" : "idle"
  }
  if (isPending) {
    return "pending"
  }
  if (previewError) {
    return "error"
  }
  return previewResultExists ? "success" : "idle"
}
