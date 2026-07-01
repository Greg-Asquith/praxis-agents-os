// apps/web/src/features/conversations/api/create-conversation-stream.ts

import type { ConversationCreateRequest } from "@/features/conversations/types"
import { apiFetch } from "@/lib/api/client"

type StreamRequestOptions = {
  signal?: AbortSignal
}

export function createConversationStream(
  payload: ConversationCreateRequest,
  options: StreamRequestOptions = {}
) {
  return apiFetch("/conversations/", {
    body: payload,
    headers: { Accept: "text/event-stream" },
    method: "POST",
    signal: options.signal ?? null,
  })
}
