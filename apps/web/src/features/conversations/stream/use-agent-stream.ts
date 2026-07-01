// apps/web/src/features/conversations/stream/use-agent-stream.ts

import { useCallback, useEffect, useReducer, useRef } from "react"
import { useQueryClient, type QueryClient } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import { createConversationStream } from "@/features/conversations/api/create-conversation-stream"
import { createTurnStream } from "@/features/conversations/api/create-turn-stream"
import { resumeRunStream } from "@/features/conversations/api/resume-run-stream"
import type {
  AgentRunStatus,
  AgentRunResumeRequest,
  ConversationCreateRequest,
  ConversationTurnCreateRequest,
} from "@/features/conversations/types"
import {
  agentStreamReducer,
  initialAgentStreamState,
} from "@/features/conversations/stream/reducer"
import { parseSseStream } from "@/features/conversations/stream/sse"
import {
  STREAM_PROTOCOL_VERSION,
  STREAM_VERSION_HEADER,
  type StreamError,
} from "@/features/conversations/stream/protocol"
import { ApiError, parseApiError } from "@/lib/api/errors"

type SendTurnInput = {
  conversationId: string
  payload: ConversationTurnCreateRequest
}

type ResumeRunInput = {
  runId: string
  payload: AgentRunResumeRequest
}

type StreamRequest = (signal: AbortSignal) => Promise<Response>

type UseAgentStreamOptions = {
  onConversationCreated?: (conversationId: string) => void
}

const STREAMING_STATUSES = new Set(["pending", "running", "awaiting_approval"])

export function useAgentStream({ onConversationCreated }: UseAgentStreamOptions = {}) {
  const queryClient = useQueryClient()
  const abortControllerRef = useRef<AbortController | null>(null)
  const [state, dispatch] = useReducer(agentStreamReducer, initialAgentStreamState)

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort()
      abortControllerRef.current = null
    }
  }, [])

  const runStream = useCallback(
    async (request: StreamRequest) => {
      if (abortControllerRef.current !== null) {
        throw new Error("An agent stream is already running.")
      }

      const abortController = new AbortController()
      abortControllerRef.current = abortController
      dispatch({ type: "start" })

      let observedConversationId: string | null = null
      let observedRunId: string | null = null
      let observedDoneStatus: AgentRunStatus | null = null

      try {
        const response = await request(abortController.signal)
        await assertStreamResponse(response)

        for await (const streamEvent of parseSseStream(response.body)) {
          observedConversationId = streamEvent.data.conversation_id
          observedRunId = streamEvent.data.run_id
          if (streamEvent.event === "done") {
            observedDoneStatus = streamEvent.data.status
          }
          dispatch({ type: "event", event: streamEvent })
          if (streamEvent.event === "conversation.created") {
            onConversationCreated?.(streamEvent.data.conversation.id)
          }
        }
      } catch (error) {
        if (isAbortError(error)) {
          return
        }

        dispatch({ type: "fail", error: toStreamError(error) })
        throw error
      } finally {
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null
        }
        await invalidateStreamQueries(queryClient, observedConversationId)
        if (
          observedConversationId !== null &&
          observedRunId !== null &&
          shouldClearSettledStream(observedDoneStatus)
        ) {
          dispatch({
            type: "resetSettledRun",
            conversationId: observedConversationId,
            runId: observedRunId,
          })
        }
      }
    },
    [onConversationCreated, queryClient]
  )

  const sendFirstMessage = useCallback(
    (payload: ConversationCreateRequest) =>
      runStream((signal) => createConversationStream(payload, { signal })),
    [runStream]
  )

  const sendTurn = useCallback(
    ({ conversationId, payload }: SendTurnInput) =>
      runStream((signal) => createTurnStream({ conversationId, payload }, { signal })),
    [runStream]
  )

  const resumeRun = useCallback(
    ({ runId, payload }: ResumeRunInput) =>
      runStream((signal) => resumeRunStream({ runId, payload }, { signal })),
    [runStream]
  )

  const abort = useCallback(() => {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
  }, [])

  const reset = useCallback(() => {
    dispatch({ type: "reset" })
  }, [])

  return {
    ...state,
    abort,
    isStreaming: !state.done && STREAMING_STATUSES.has(state.status),
    reset,
    resumeRun,
    sendFirstMessage,
    sendTurn,
  }
}

async function assertStreamResponse(response: Response) {
  if (!response.ok) {
    throw await parseApiError(response)
  }

  const version = response.headers.get(STREAM_VERSION_HEADER)
  if (version !== STREAM_PROTOCOL_VERSION) {
    throw new Error(
      `Unsupported agent stream version "${version ?? "missing"}"; expected "${STREAM_PROTOCOL_VERSION}".`
    )
  }
}

function toStreamError(error: unknown): StreamError {
  if (error instanceof ApiError) {
    return { code: `http_${String(error.status)}`, message: error.message }
  }

  if (error instanceof Error) {
    return { code: "stream_failed", message: error.message }
  }

  return { code: "stream_failed", message: "The agent stream failed." }
}

async function invalidateStreamQueries(queryClient: QueryClient, conversationId: string | null) {
  const invalidations = [
    queryClient.invalidateQueries({ queryKey: conversationsQueryKeys.lists() }),
  ]

  if (conversationId !== null) {
    invalidations.push(
      queryClient.invalidateQueries({
        queryKey: conversationsQueryKeys.messages(conversationId),
      }),
      queryClient.invalidateQueries({
        queryKey: conversationsQueryKeys.activeRun(conversationId),
      })
    )
  }

  await Promise.all(invalidations)
}

function isAbortError(error: unknown) {
  return error instanceof Error && error.name === "AbortError"
}

function shouldClearSettledStream(status: AgentRunStatus | null) {
  return status === "completed" || status === "cancelled"
}
