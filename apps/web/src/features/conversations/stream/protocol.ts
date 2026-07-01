// apps/web/src/features/conversations/stream/protocol.ts

import type {
  AgentRunStatus,
  Conversation,
} from "@/features/conversations/types"

export const STREAM_PROTOCOL_VERSION = "1"
export const STREAM_VERSION_HEADER = "X-Praxis-Stream-Version"

export const STREAM_EVENT_NAMES = [
  "conversation.created",
  "conversation.updated",
  "run.status",
  "message.start",
  "message.delta",
  "message.end",
  "tool.call",
  "tool.result",
  "tool.approval_required",
  "error",
  "done",
] as const

export type StreamEventName = (typeof STREAM_EVENT_NAMES)[number]

const STREAM_EVENT_NAME_SET: ReadonlySet<string> = new Set(STREAM_EVENT_NAMES)

export type StreamEnvelope = {
  run_id: string
  conversation_id: string
  seq: number
}

export type StreamError = {
  code: string
  message: string
}

export type StreamEvent =
  | {
      event: "conversation.created"
      data: StreamEnvelope & { conversation: Conversation }
    }
  | {
      event: "conversation.updated"
      data: StreamEnvelope & { conversation: Conversation }
    }
  | {
      event: "run.status"
      data: StreamEnvelope & { status: AgentRunStatus }
    }
  | {
      event: "message.start"
      data: StreamEnvelope & { message_id: string; role: "assistant" }
    }
  | {
      event: "message.delta"
      data: StreamEnvelope & { message_id: string; text: string }
    }
  | {
      event: "message.end"
      data: StreamEnvelope & { message_id: string }
    }
  | {
      event: "tool.call"
      data: StreamEnvelope & { tool_call_id: string; name: string; args: unknown }
    }
  | {
      event: "tool.result"
      data: StreamEnvelope & {
        tool_call_id: string
        name?: string | null
        result: unknown
      }
    }
  | {
      event: "tool.approval_required"
      data: StreamEnvelope & { tool_call_id: string; name: string; args: unknown }
    }
  | {
      event: "error"
      data: StreamEnvelope & StreamError
    }
  | {
      event: "done"
      data: StreamEnvelope & { status: AgentRunStatus }
    }

export function isStreamEventName(value: string): value is StreamEventName {
  return STREAM_EVENT_NAME_SET.has(value)
}
