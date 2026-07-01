// apps/web/src/features/conversations/api/create-turn-stream.ts

import type { ConversationTurnCreateRequest } from "@/features/conversations/types"
import { apiFetch } from "@/lib/api/client"

type StreamRequestOptions = {
  signal?: AbortSignal
}

type CreateTurnStreamInput = {
  conversationId: string
  payload: ConversationTurnCreateRequest
}

export function createTurnStream(
  { conversationId, payload }: CreateTurnStreamInput,
  options: StreamRequestOptions = {}
) {
  return apiFetch(`/conversations/${conversationId}/turns`, {
    body: payload,
    headers: { Accept: "text/event-stream" },
    method: "POST",
    signal: options.signal ?? null,
  })
}
