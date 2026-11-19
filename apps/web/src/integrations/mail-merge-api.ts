// apps/web/src/integrations/mail-merge-api.ts

import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

export type MailMergeStatus =
  "queued" | "sending" | "paused" | "completed" | "cancelled" | "stopped"

export type MailMergeRowState = "waiting" | "sent" | "failed" | "unverified" | "skipped"

export type MailMergeProgress = {
  id: string
  provider_key: string
  sender_address: string
  status: MailMergeStatus
  stop_reason: string | null
  created_at: string
  finished_at: string | null
  estimated_finish: string | null
  resumes_at: string | null
  counts: Record<MailMergeRowState | "total", number>
  recipients: {
    position: number
    email: string
    state: MailMergeRowState
    reason: string | null
    sent_at: string | null
  }[]
}

export type MailMergeAction = "pause" | "resume" | "cancel"

const ACTIVE: ReadonlySet<MailMergeStatus> = new Set(["queued", "sending"])

const queryKeys = createWorkspaceScopedQueryKeys("mail-merges")

export function mailMergeQueryOptions(mergeId: string) {
  return queryOptions({
    queryKey: queryKeys.detail(mergeId),
    queryFn: () => apiRequest<MailMergeProgress>(`/mail-merges/${mergeId}`),
    // Every few seconds while sending, rarely while paused, never once it has ended or failed.
    refetchInterval: (query) => {
      if (query.state.status === "error") return false
      const status = query.state.data?.status
      if (!status || ACTIVE.has(status)) return 3_000
      return status === "paused" ? 30_000 : false
    },
    retry: false,
  })
}

export function useMailMergeAction(mergeId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (action: MailMergeAction) =>
      apiRequest<MailMergeProgress>(`/mail-merges/${mergeId}/${action}`, { method: "POST" }),
    onSuccess: (progress) => {
      queryClient.setQueryData(queryKeys.detail(mergeId), progress)
    },
  })
}
