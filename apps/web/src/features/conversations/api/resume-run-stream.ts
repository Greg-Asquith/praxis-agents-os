// apps/web/src/features/conversations/api/resume-run-stream.ts

import type { AgentRunResumeRequest } from "@/features/conversations/types"
import { apiFetch } from "@/lib/api/client"

type StreamRequestOptions = {
  signal?: AbortSignal
}

type ResumeRunStreamInput = {
  runId: string
  payload: AgentRunResumeRequest
}

export function resumeRunStream(
  { runId, payload }: ResumeRunStreamInput,
  options: StreamRequestOptions = {}
) {
  return apiFetch(`/agent-runs/${runId}/resume`, {
    body: payload,
    headers: { Accept: "text/event-stream" },
    method: "POST",
    signal: options.signal ?? null,
  })
}
