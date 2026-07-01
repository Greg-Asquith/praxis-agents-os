// apps/web/src/features/conversations/stream/reducer.ts

import type { AgentRunStatus, Conversation } from "@/features/conversations/types"
import type { StreamError, StreamEvent } from "@/features/conversations/stream/protocol"

export type AgentStreamStatus = "idle" | AgentRunStatus

export type ChatMessageDraft = {
  id: string
  role: "assistant"
  text: string
  status: "streaming" | "complete"
}

export type ToolCallState = {
  tool_call_id: string
  name: string
  args: unknown
  result: unknown
  status: "running" | "awaiting_approval" | "completed"
}

export type ApprovalState = {
  tool_call_id: string
  name: string
  args: unknown
  status: "pending"
}

export type AgentStreamState = {
  conversation: Conversation | null
  conversationId: string | null
  runId: string | null
  status: AgentStreamStatus
  messages: ChatMessageDraft[]
  toolCalls: Record<string, ToolCallState>
  approvals: Record<string, ApprovalState>
  error: StreamError | null
  done: boolean
  lastSeq: number
}

export type AgentStreamAction =
  | { type: "start" }
  | { type: "reset" }
  | { type: "resetSettledRun"; runId: string; conversationId: string }
  | { type: "event"; event: StreamEvent }
  | { type: "fail"; error: StreamError }

export const initialAgentStreamState: AgentStreamState = {
  conversation: null,
  conversationId: null,
  runId: null,
  status: "idle",
  messages: [],
  toolCalls: {},
  approvals: {},
  error: null,
  done: false,
  lastSeq: 0,
}

export function agentStreamReducer(
  state: AgentStreamState,
  action: AgentStreamAction
): AgentStreamState {
  switch (action.type) {
    case "start":
      return { ...initialAgentStreamState, status: "pending" }
    case "reset":
      return initialAgentStreamState
    case "resetSettledRun":
      if (
        state.runId !== action.runId ||
        state.conversationId !== action.conversationId ||
        !state.done
      ) {
        return state
      }

      return initialAgentStreamState
    case "fail":
      return withStreamError(state, action.error)
    case "event":
      return reduceStreamEvent(state, action.event)
  }
}

export function reduceStreamEvent(
  state: AgentStreamState,
  streamEvent: StreamEvent
): AgentStreamState {
  if (state.done && streamEvent.event !== "conversation.updated") {
    return state
  }

  if (streamEvent.data.seq <= state.lastSeq) {
    return withStreamError(state, {
      code: "stream_sequence_out_of_order",
      message: `Stream sequence moved from ${String(state.lastSeq)} to ${String(
        streamEvent.data.seq
      )}.`,
    })
  }

  const nextState = {
    ...state,
    conversationId: streamEvent.data.conversation_id,
    runId: streamEvent.data.run_id,
    lastSeq: streamEvent.data.seq,
  }

  switch (streamEvent.event) {
    case "conversation.created":
    case "conversation.updated":
      return {
        ...nextState,
        conversation: streamEvent.data.conversation,
        conversationId: streamEvent.data.conversation.id,
      }
    case "run.status":
      return { ...nextState, status: streamEvent.data.status }
    case "message.start":
      return {
        ...nextState,
        messages: upsertMessageStart(
          nextState.messages,
          streamEvent.data.message_id,
          streamEvent.data.role
        ),
      }
    case "message.delta":
      return {
        ...nextState,
        messages: appendMessageDelta(
          nextState.messages,
          streamEvent.data.message_id,
          streamEvent.data.text
        ),
      }
    case "message.end":
      return {
        ...nextState,
        messages: completeMessage(nextState.messages, streamEvent.data.message_id),
      }
    case "tool.call":
      return {
        ...nextState,
        toolCalls: {
          ...nextState.toolCalls,
          [streamEvent.data.tool_call_id]: {
            args: streamEvent.data.args,
            name: streamEvent.data.name,
            result: null,
            status: "running",
            tool_call_id: streamEvent.data.tool_call_id,
          },
        },
      }
    case "tool.result": {
      const existing = nextState.toolCalls[streamEvent.data.tool_call_id]
      return {
        ...nextState,
        toolCalls: {
          ...nextState.toolCalls,
          [streamEvent.data.tool_call_id]: {
            args: existing?.args,
            name: streamEvent.data.name ?? existing?.name ?? "tool",
            result: streamEvent.data.result,
            status: "completed",
            tool_call_id: streamEvent.data.tool_call_id,
          },
        },
      }
    }
    case "tool.approval_required": {
      const approval = {
        args: streamEvent.data.args,
        name: streamEvent.data.name,
        status: "pending" as const,
        tool_call_id: streamEvent.data.tool_call_id,
      }

      return {
        ...nextState,
        approvals: {
          ...nextState.approvals,
          [streamEvent.data.tool_call_id]: approval,
        },
        status: "awaiting_approval",
        toolCalls: {
          ...nextState.toolCalls,
          [streamEvent.data.tool_call_id]: {
            args: streamEvent.data.args,
            name: streamEvent.data.name,
            result: null,
            status: "awaiting_approval",
            tool_call_id: streamEvent.data.tool_call_id,
          },
        },
      }
    }
    case "error":
      return withStreamError(nextState, {
        code: streamEvent.data.code,
        message: streamEvent.data.message,
      })
    case "done":
      return {
        ...nextState,
        done: true,
        status: streamEvent.data.status,
      }
  }
}

function upsertMessageStart(
  messages: ChatMessageDraft[],
  messageId: string,
  role: "assistant"
): ChatMessageDraft[] {
  const nextMessage: ChatMessageDraft = {
    id: messageId,
    role,
    status: "streaming",
    text: "",
  }
  const existingIndex = messages.findIndex((message) => message.id === messageId)
  if (existingIndex === -1) {
    return [...messages, nextMessage]
  }

  return messages.map((message) => (message.id === messageId ? nextMessage : message))
}

function appendMessageDelta(
  messages: ChatMessageDraft[],
  messageId: string,
  text: string
): ChatMessageDraft[] {
  const existingIndex = messages.findIndex((message) => message.id === messageId)
  if (existingIndex === -1) {
    return [
      ...messages,
      {
        id: messageId,
        role: "assistant" as const,
        status: "streaming" as const,
        text,
      },
    ]
  }

  return messages.map((message) =>
    message.id === messageId ? { ...message, text: `${message.text}${text}` } : message
  )
}

function completeMessage(messages: ChatMessageDraft[], messageId: string): ChatMessageDraft[] {
  return messages.map((message) =>
    message.id === messageId ? { ...message, status: "complete" as const } : message
  )
}

function withStreamError(state: AgentStreamState, error: StreamError): AgentStreamState {
  return {
    ...state,
    done: true,
    error,
    status: "failed",
  }
}
