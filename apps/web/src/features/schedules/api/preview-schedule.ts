// apps/web/src/features/schedules/api/preview-schedule.ts

import { useMutation } from "@tanstack/react-query"

import type { SchedulePreviewRequest, SchedulePreviewResponse } from "@/features/schedules/types"
import { apiRequest } from "@/lib/api/client"

async function previewSchedule(payload: SchedulePreviewRequest) {
  return apiRequest<SchedulePreviewResponse>("/schedules/preview", {
    body: payload,
    method: "POST",
  })
}

export function usePreviewScheduleMutation() {
  return useMutation({
    mutationFn: previewSchedule,
  })
}
