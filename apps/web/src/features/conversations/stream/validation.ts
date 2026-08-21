// apps/web/src/features/conversations/stream/validation.ts

import type {
  AgentRunStatus,
  Conversation,
  PendingDelegatedApproval,
} from "@/features/conversations/types"
import type {
  MessageChannel,
  StreamEvent,
  StreamEventName,
  StreamRunStatus,
  WorkflowState,
} from "@/features/conversations/stream/protocol"
import { isNonNegativeInteger, isOneOf, isPositiveInteger, isRecord } from "@/lib/guards"

export const AGENT_RUN_STATUSES: ReadonlySet<AgentRunStatus> = new Set([
  "pending",
  "running",
  "awaiting_approval",
  "completed",
  "failed",
  "cancelled",
])
export const STREAM_RUN_STATUSES: ReadonlySet<StreamRunStatus> = new Set([
  ...AGENT_RUN_STATUSES,
  "queued",
])

export const CONVERSATION_SOURCES: ReadonlySet<Conversation["source"]> = new Set([
  "direct",
  "scheduled",
  "delegated",
  "event",
])

export const MESSAGE_CHANNELS: ReadonlySet<MessageChannel> = new Set(["text", "thinking"])
export const WORKFLOW_STATES: ReadonlySet<WorkflowState> = new Set([
  "started",
  "completed",
  "failed",
])

type StreamEnvelope = {
  run_id: string
  conversation_id: string
  seq: number
}

export function parseStreamEvent(eventName: StreamEventName, value: unknown): StreamEvent {
  const data = requiredRecord(eventName, "data", value)
  const envelope = parseEnvelope(eventName, data)

  switch (eventName) {
    case "conversation.created":
      return {
        event: "conversation.created",
        data: {
          ...envelope,
          conversation: parseConversation(eventName, data["conversation"]),
        },
      }
    case "conversation.updated":
      return {
        event: "conversation.updated",
        data: {
          ...envelope,
          conversation: parseConversation(eventName, data["conversation"]),
        },
      }
    case "run.status":
      return {
        event: "run.status",
        data: {
          ...envelope,
          status: requiredStreamRunStatus(eventName, "data.status", data["status"]),
        },
      }
    case "message.start": {
      const channel = requiredEnum(
        eventName,
        "data.channel",
        data["channel"],
        MESSAGE_CHANNELS,
        "a supported message channel"
      )
      return {
        event: "message.start",
        data: {
          ...envelope,
          message_id: requiredNonEmptyString(eventName, "data.message_id", data["message_id"]),
          role: requiredLiteral(eventName, "data.role", data["role"], "assistant"),
          channel,
        },
      }
    }
    case "message.delta":
      return {
        event: "message.delta",
        data: {
          ...envelope,
          message_id: requiredNonEmptyString(eventName, "data.message_id", data["message_id"]),
          text: requiredString(eventName, "data.text", data["text"]),
        },
      }
    case "message.end":
      return {
        event: "message.end",
        data: {
          ...envelope,
          message_id: requiredNonEmptyString(eventName, "data.message_id", data["message_id"]),
        },
      }
    case "tool.call": {
      const parentToolCallId = optionalNullableNonEmptyString(
        eventName,
        data,
        "parent_tool_call_id"
      )
      return {
        event: "tool.call",
        data: {
          ...envelope,
          tool_call_id: requiredNonEmptyString(
            eventName,
            "data.tool_call_id",
            data["tool_call_id"]
          ),
          name: requiredNonEmptyString(eventName, "data.name", data["name"]),
          args: requiredField(eventName, data, "args"),
          ...(parentToolCallId === undefined ? {} : { parent_tool_call_id: parentToolCallId }),
        },
      }
    }
    case "tool.result": {
      const name = requiredNullableNonEmptyString(eventName, "data.name", data["name"])
      const parentToolCallId = optionalNullableNonEmptyString(
        eventName,
        data,
        "parent_tool_call_id"
      )
      return {
        event: "tool.result",
        data: {
          ...envelope,
          tool_call_id: requiredNonEmptyString(
            eventName,
            "data.tool_call_id",
            data["tool_call_id"]
          ),
          name,
          result: requiredField(eventName, data, "result"),
          ...(parentToolCallId === undefined ? {} : { parent_tool_call_id: parentToolCallId }),
        },
      }
    }
    case "tool.approval_required": {
      const replayArgs = optionalField(data, "replay_args")
      const parentToolCallId = optionalNullableNonEmptyString(
        eventName,
        data,
        "parent_tool_call_id"
      )
      const delegation = optionalNullableDelegation(eventName, data)
      const derivedFromUntrusted = optionalNullableBoolean(
        eventName,
        data,
        "derived_from_untrusted"
      )
      const taintSources = optionalTaintSources(eventName, data)
      return {
        event: "tool.approval_required",
        data: {
          ...envelope,
          tool_call_id: requiredNonEmptyString(
            eventName,
            "data.tool_call_id",
            data["tool_call_id"]
          ),
          name: requiredNonEmptyString(eventName, "data.name", data["name"]),
          args: requiredField(eventName, data, "args"),
          ...(parentToolCallId === undefined ? {} : { parent_tool_call_id: parentToolCallId }),
          ...(replayArgs.present ? { replay_args: replayArgs.value } : {}),
          ...(delegation === undefined ? {} : { delegation }),
          ...(derivedFromUntrusted === undefined
            ? {}
            : { derived_from_untrusted: derivedFromUntrusted }),
          ...(taintSources === undefined ? {} : { taint_sources: taintSources }),
        },
      }
    }
    case "workflow.state": {
      const outputExcerpt = optionalNullableString(eventName, data, "output_excerpt")
      const errorExcerpt = optionalNullableString(eventName, data, "error_excerpt")
      return {
        event: "workflow.state",
        data: {
          ...envelope,
          tool_call_id: requiredNonEmptyString(
            eventName,
            "data.tool_call_id",
            data["tool_call_id"]
          ),
          state: requiredEnum(
            eventName,
            "data.state",
            data["state"],
            WORKFLOW_STATES,
            "a supported workflow state"
          ),
          ...(outputExcerpt === undefined ? {} : { output_excerpt: outputExcerpt }),
          ...(errorExcerpt === undefined ? {} : { error_excerpt: errorExcerpt }),
        },
      }
    }
    case "error":
      return {
        event: "error",
        data: {
          ...envelope,
          code: requiredNonEmptyString(eventName, "data.code", data["code"]),
          message: requiredString(eventName, "data.message", data["message"]),
        },
      }
    case "done":
      return {
        event: "done",
        data: {
          ...envelope,
          status: requiredAgentRunStatus(eventName, "data.status", data["status"]),
        },
      }
  }
}

function optionalTaintSources(eventName: StreamEventName, data: Record<string, unknown>) {
  if (!("taint_sources" in data)) {
    return undefined
  }
  const value = data["taint_sources"]
  if (value === null) {
    return undefined
  }
  if (!Array.isArray(value)) {
    invalidField(eventName, "data.taint_sources", "must be an array")
  }
  return value.map((source, index) => {
    if (!isRecord(source)) {
      invalidField(eventName, `data.taint_sources[${String(index)}]`, "must be an object")
    }
    return {
      source_kind: requiredNonEmptyString(
        eventName,
        `data.taint_sources[${String(index)}].source_kind`,
        source["source_kind"]
      ),
      source_ref: requiredNonEmptyString(
        eventName,
        `data.taint_sources[${String(index)}].source_ref`,
        source["source_ref"]
      ),
    }
  })
}

function parseEnvelope(eventName: StreamEventName, data: Record<string, unknown>): StreamEnvelope {
  return {
    run_id: requiredNonEmptyString(eventName, "data.run_id", data["run_id"]),
    conversation_id: requiredNonEmptyString(
      eventName,
      "data.conversation_id",
      data["conversation_id"]
    ),
    seq: requiredPositiveInteger(eventName, "data.seq", data["seq"]),
  }
}

function parseConversation(eventName: StreamEventName, value: unknown): Conversation {
  const field = "data.conversation"
  const conversation = requiredRecord(eventName, field, value)

  return {
    id: requiredNonEmptyString(eventName, `${field}.id`, conversation["id"]),
    user_id: requiredNonEmptyString(eventName, `${field}.user_id`, conversation["user_id"]),
    workspace_id: requiredNonEmptyString(
      eventName,
      `${field}.workspace_id`,
      conversation["workspace_id"]
    ),
    created_by: requiredNonEmptyString(
      eventName,
      `${field}.created_by`,
      conversation["created_by"]
    ),
    title: requiredNullableString(eventName, `${field}.title`, conversation["title"]),
    description: requiredNullableString(
      eventName,
      `${field}.description`,
      conversation["description"]
    ),
    status: requiredNonEmptyString(eventName, `${field}.status`, conversation["status"]),
    metadata: requiredNullableRecord(eventName, `${field}.metadata`, conversation["metadata"]),
    unread: requiredBoolean(eventName, `${field}.unread`, conversation["unread"]),
    source: requiredEnum(
      eventName,
      `${field}.source`,
      conversation["source"],
      CONVERSATION_SOURCES,
      "a supported conversation source"
    ),
    last_message_at: requiredNullableString(
      eventName,
      `${field}.last_message_at`,
      conversation["last_message_at"]
    ),
    active_agent_id: requiredNullableString(
      eventName,
      `${field}.active_agent_id`,
      conversation["active_agent_id"]
    ),
    agent_slug: requiredNullableString(
      eventName,
      `${field}.agent_slug`,
      conversation["agent_slug"]
    ),
    agent_name: optionalNullableString(eventName, conversation, "agent_name") ?? null,
    active_run_id: optionalNullableString(eventName, conversation, "active_run_id") ?? null,
    active_run_status:
      optionalNullableAgentRunStatus(eventName, conversation, "active_run_status") ?? null,
    needs_approval: optionalBoolean(eventName, conversation, "needs_approval") ?? false,
    created_at: requiredNonEmptyString(
      eventName,
      `${field}.created_at`,
      conversation["created_at"]
    ),
    updated_at: requiredNonEmptyString(
      eventName,
      `${field}.updated_at`,
      conversation["updated_at"]
    ),
  }
}

function parseDelegation(eventName: StreamEventName, value: unknown): PendingDelegatedApproval {
  const field = "data.delegation"
  const delegation = requiredRecord(eventName, field, value)
  return {
    parent_tool_call_id: requiredNonEmptyString(
      eventName,
      `${field}.parent_tool_call_id`,
      delegation["parent_tool_call_id"]
    ),
    child_agent_id: requiredNonEmptyString(
      eventName,
      `${field}.child_agent_id`,
      delegation["child_agent_id"]
    ),
    child_agent_name: requiredNonEmptyString(
      eventName,
      `${field}.child_agent_name`,
      delegation["child_agent_name"]
    ),
    child_conversation_id: requiredNonEmptyString(
      eventName,
      `${field}.child_conversation_id`,
      delegation["child_conversation_id"]
    ),
    child_run_id: requiredNonEmptyString(
      eventName,
      `${field}.child_run_id`,
      delegation["child_run_id"]
    ),
    pending_approval_count: requiredNonNegativeInteger(
      eventName,
      `${field}.pending_approval_count`,
      delegation["pending_approval_count"]
    ),
  }
}

function requiredRecord(
  eventName: StreamEventName,
  field: string,
  value: unknown
): Record<string, unknown> {
  if (!isRecord(value)) {
    invalidField(eventName, field, "must be a JSON object")
  }
  return value
}

function requiredNullableRecord(
  eventName: StreamEventName,
  field: string,
  value: unknown
): Record<string, unknown> | null {
  if (value === null) {
    return null
  }
  return requiredRecord(eventName, field, value)
}

function requiredString(eventName: StreamEventName, field: string, value: unknown): string {
  if (typeof value !== "string") {
    invalidField(eventName, field, "must be a string")
  }
  return value
}

function requiredNonEmptyString(eventName: StreamEventName, field: string, value: unknown): string {
  const parsed = requiredString(eventName, field, value)
  if (parsed.length === 0) {
    invalidField(eventName, field, "must be a non-empty string")
  }
  return parsed
}

function requiredNullableString(
  eventName: StreamEventName,
  field: string,
  value: unknown
): string | null {
  if (value === null) {
    return null
  }
  return requiredString(eventName, field, value)
}

function requiredNullableNonEmptyString(
  eventName: StreamEventName,
  field: string,
  value: unknown
): string | null {
  if (value === null) {
    return null
  }
  return requiredNonEmptyString(eventName, field, value)
}

function requiredBoolean(eventName: StreamEventName, field: string, value: unknown): boolean {
  if (typeof value !== "boolean") {
    invalidField(eventName, field, "must be a boolean")
  }
  return value
}

function requiredPositiveInteger(
  eventName: StreamEventName,
  field: string,
  value: unknown
): number {
  if (!isPositiveInteger(value)) {
    invalidField(eventName, field, "must be a positive integer")
  }
  return value
}

function requiredNonNegativeInteger(
  eventName: StreamEventName,
  field: string,
  value: unknown
): number {
  if (!isNonNegativeInteger(value)) {
    invalidField(eventName, field, "must be a non-negative integer")
  }
  return value
}

function requiredEnum<T extends string>(
  eventName: StreamEventName,
  field: string,
  value: unknown,
  values: ReadonlySet<T>,
  expectation: string
): T {
  if (!isOneOf(values, value)) {
    invalidField(eventName, field, `must be ${expectation}`)
  }
  return value
}

function requiredLiteral<const Value extends string>(
  eventName: StreamEventName,
  field: string,
  value: unknown,
  expected: Value
): Value {
  if (value !== expected) {
    invalidField(eventName, field, `must be "${expected}"`)
  }
  return expected
}

function requiredAgentRunStatus(
  eventName: StreamEventName,
  field: string,
  value: unknown
): AgentRunStatus {
  return requiredEnum(eventName, field, value, AGENT_RUN_STATUSES, "a supported run status")
}

function requiredStreamRunStatus(
  eventName: StreamEventName,
  field: string,
  value: unknown
): StreamRunStatus {
  return requiredEnum(eventName, field, value, STREAM_RUN_STATUSES, "a supported stream run status")
}

function requiredNullableAgentRunStatus(
  eventName: StreamEventName,
  field: string,
  value: unknown
): AgentRunStatus | null {
  return value === null ? null : requiredAgentRunStatus(eventName, field, value)
}

function optionalNullableAgentRunStatus(
  eventName: StreamEventName,
  record: Record<string, unknown>,
  key: string
): AgentRunStatus | null | undefined {
  if (!Object.hasOwn(record, key)) {
    return undefined
  }
  return requiredNullableAgentRunStatus(eventName, `data.conversation.${key}`, record[key])
}

function optionalBoolean(
  eventName: StreamEventName,
  record: Record<string, unknown>,
  key: string
): boolean | undefined {
  if (!Object.hasOwn(record, key)) {
    return undefined
  }
  return requiredBoolean(eventName, `data.conversation.${key}`, record[key])
}

function optionalNullableBoolean(
  eventName: StreamEventName,
  record: Record<string, unknown>,
  key: string
): boolean | undefined {
  if (!Object.hasOwn(record, key)) {
    return undefined
  }
  if (record[key] === null) {
    return undefined
  }
  return requiredBoolean(eventName, `data.${key}`, record[key])
}

function optionalNullableNonEmptyString(
  eventName: StreamEventName,
  record: Record<string, unknown>,
  key: string
): string | undefined {
  if (!Object.hasOwn(record, key)) {
    return undefined
  }
  if (record[key] === null) {
    return undefined
  }
  return requiredNonEmptyString(eventName, `data.${key}`, record[key])
}

function optionalNullableString(
  eventName: StreamEventName,
  record: Record<string, unknown>,
  key: string
): string | null | undefined {
  if (!Object.hasOwn(record, key)) {
    return undefined
  }
  return requiredNullableString(eventName, `data.${key}`, record[key])
}

function optionalNullableDelegation(
  eventName: StreamEventName,
  record: Record<string, unknown>
): PendingDelegatedApproval | null | undefined {
  if (!Object.hasOwn(record, "delegation")) {
    return undefined
  }
  return record["delegation"] === null ? null : parseDelegation(eventName, record["delegation"])
}

function requiredField(
  eventName: StreamEventName,
  record: Record<string, unknown>,
  key: string
): unknown {
  if (!Object.hasOwn(record, key)) {
    invalidField(eventName, `data.${key}`, "is required")
  }
  return record[key]
}

function optionalField(
  record: Record<string, unknown>,
  key: string
): { present: false } | { present: true; value: unknown } {
  return Object.hasOwn(record, key) ? { present: true, value: record[key] } : { present: false }
}

function invalidField(eventName: StreamEventName, field: string, expectation: string): never {
  throw new Error(`Invalid SSE event "${eventName}": field "${field}" ${expectation}.`)
}
