// apps/web/src/features/conversations/stream/reducer.ts

import type {
  AgentRunStatus,
  Conversation,
  PendingDelegatedApproval,
  TaintSource,
} from "@/features/conversations/types"
import type {
  MessageChannel,
  StreamError,
  StreamEvent,
  WorkflowState,
} from "@/features/conversations/stream/protocol"

type AgentStreamStatus = "idle" | AgentRunStatus

export type ChatMessageDraft = {
  channel: MessageChannel
  id: string
  role: "assistant"
  text: string
  status: "streaming" | "complete"
  timelineSequence: number
}

export type ToolCallState = {
  tool_call_id: string
  name: string
  args: unknown
  result: unknown
  status: "running" | "awaiting_approval" | "completed" | "failed" | "denied"
  timelineSequence: number
  parentToolCallId?: string
  workflowState?: WorkflowState
  workflowOutputExcerpt?: string | null
  workflowErrorExcerpt?: string | null
}

export type ApprovalState = {
  tool_call_id: string
  name: string
  args: unknown
  replay_args?: unknown
  delegation?: PendingDelegatedApproval | null
  derived_from_untrusted?: boolean
  taint_sources?: TaintSource[]
  status: "pending"
}

export type AgentStreamState = {
  isConnected: boolean
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
  nextTimelineSequence: number
}

export type LiveTimelineItem =
  | { kind: "text"; message: ChatMessageDraft; sequence: number }
  | { kind: "tool"; toolCall: ToolCallState; sequence: number }

export type AgentStreamAction =
  | { type: "start" }
  | { type: "connect" }
  | { type: "disconnect" }
  | { type: "abort" }
  | { type: "reset" }
  | { type: "finishClosedStream" }
  | { type: "event"; event: StreamEvent }
  | { type: "fail"; error: StreamError }

export const initialAgentStreamState: AgentStreamState = {
  isConnected: false,
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
  nextTimelineSequence: 0,
}

export function agentStreamReducer(
  state: AgentStreamState,
  action: AgentStreamAction
): AgentStreamState {
  switch (action.type) {
    case "start":
      return { ...initialAgentStreamState, status: "pending" }
    case "connect":
      return { ...state, isConnected: true }
    case "disconnect":
      return { ...state, isConnected: false }
    case "abort":
      if (state.status === "idle" || state.done) {
        return state
      }

      return { ...state, isConnected: false, done: true }
    case "reset":
      return initialAgentStreamState
    case "finishClosedStream":
      return { ...state, isConnected: false, done: true }
    case "fail":
      return withStreamError(state, action.error)
    case "event":
      return reduceStreamEvent(state, action.event)
  }
}

function reduceStreamEvent(state: AgentStreamState, streamEvent: StreamEvent): AgentStreamState {
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
    case "message.start": {
      const existing = nextState.messages.find(
        (message) => message.id === streamEvent.data.message_id
      )
      const timelineSequence = existing?.timelineSequence ?? nextState.nextTimelineSequence
      return {
        ...nextState,
        messages: upsertMessageStart(
          nextState.messages,
          streamEvent.data.message_id,
          streamEvent.data.role,
          streamEvent.data.channel,
          timelineSequence
        ),
        nextTimelineSequence: existing
          ? nextState.nextTimelineSequence
          : nextState.nextTimelineSequence + 1,
      }
    }
    case "message.delta": {
      const existing = nextState.messages.find(
        (message) => message.id === streamEvent.data.message_id
      )
      const timelineSequence = existing?.timelineSequence ?? nextState.nextTimelineSequence
      return {
        ...nextState,
        messages: appendMessageDelta(
          nextState.messages,
          streamEvent.data.message_id,
          streamEvent.data.text,
          timelineSequence
        ),
        nextTimelineSequence: existing
          ? nextState.nextTimelineSequence
          : nextState.nextTimelineSequence + 1,
      }
    }
    case "message.end":
      return {
        ...nextState,
        messages: completeMessage(nextState.messages, streamEvent.data.message_id),
      }
    case "tool.call": {
      const existing = nextState.toolCalls[streamEvent.data.tool_call_id]
      const timelineSequence = existing?.timelineSequence ?? nextState.nextTimelineSequence
      return {
        ...nextState,
        nextTimelineSequence: existing
          ? nextState.nextTimelineSequence
          : nextState.nextTimelineSequence + 1,
        toolCalls: {
          ...nextState.toolCalls,
          [streamEvent.data.tool_call_id]: {
            args: streamEvent.data.args,
            name: streamEvent.data.name,
            result: null,
            status: "running",
            timelineSequence,
            tool_call_id: streamEvent.data.tool_call_id,
            ...(streamEvent.data.parent_tool_call_id === undefined
              ? {}
              : { parentToolCallId: streamEvent.data.parent_tool_call_id }),
            ...(existing?.workflowState === undefined
              ? {}
              : { workflowState: existing.workflowState }),
            ...(existing?.workflowOutputExcerpt === undefined
              ? {}
              : { workflowOutputExcerpt: existing.workflowOutputExcerpt }),
            ...(existing?.workflowErrorExcerpt === undefined
              ? {}
              : { workflowErrorExcerpt: existing.workflowErrorExcerpt }),
          },
        },
      }
    }
    case "tool.result": {
      const existing = nextState.toolCalls[streamEvent.data.tool_call_id]
      const timelineSequence = existing?.timelineSequence ?? nextState.nextTimelineSequence
      const parentToolCallId = streamEvent.data.parent_tool_call_id ?? existing?.parentToolCallId
      return {
        ...nextState,
        nextTimelineSequence: existing
          ? nextState.nextTimelineSequence
          : nextState.nextTimelineSequence + 1,
        toolCalls: {
          ...nextState.toolCalls,
          [streamEvent.data.tool_call_id]: {
            args: existing?.args,
            name: streamEvent.data.name ?? existing?.name ?? "tool",
            result: streamEvent.data.result,
            status: nestedResultStatus(streamEvent.data.result, parentToolCallId),
            timelineSequence,
            tool_call_id: streamEvent.data.tool_call_id,
            ...(parentToolCallId === undefined ? {} : { parentToolCallId }),
            ...(existing?.workflowState === undefined
              ? {}
              : { workflowState: existing.workflowState }),
            ...(existing?.workflowOutputExcerpt === undefined
              ? {}
              : { workflowOutputExcerpt: existing.workflowOutputExcerpt }),
            ...(existing?.workflowErrorExcerpt === undefined
              ? {}
              : { workflowErrorExcerpt: existing.workflowErrorExcerpt }),
          },
        },
      }
    }
    case "tool.approval_required": {
      const existing = nextState.toolCalls[streamEvent.data.tool_call_id]
      const timelineSequence = existing?.timelineSequence ?? nextState.nextTimelineSequence
      const parentToolCallId = streamEvent.data.parent_tool_call_id ?? existing?.parentToolCallId
      const approval = {
        args: streamEvent.data.args,
        delegation: streamEvent.data.delegation ?? null,
        name: streamEvent.data.name,
        ...(streamEvent.data.replay_args !== undefined
          ? { replay_args: streamEvent.data.replay_args }
          : {}),
        ...(streamEvent.data.derived_from_untrusted === undefined
          ? {}
          : { derived_from_untrusted: streamEvent.data.derived_from_untrusted }),
        ...(streamEvent.data.taint_sources === undefined
          ? {}
          : { taint_sources: streamEvent.data.taint_sources }),
        status: "pending" as const,
        tool_call_id: streamEvent.data.tool_call_id,
      }

      return {
        ...nextState,
        nextTimelineSequence: existing
          ? nextState.nextTimelineSequence
          : nextState.nextTimelineSequence + 1,
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
            timelineSequence,
            tool_call_id: streamEvent.data.tool_call_id,
            ...(parentToolCallId === undefined ? {} : { parentToolCallId }),
          },
        },
      }
    }
    case "workflow.state": {
      const existing = nextState.toolCalls[streamEvent.data.tool_call_id]
      const timelineSequence = existing?.timelineSequence ?? nextState.nextTimelineSequence
      const workflowStatus =
        streamEvent.data.state === "failed"
          ? "failed"
          : streamEvent.data.state === "completed"
            ? "completed"
            : "running"
      return {
        ...nextState,
        nextTimelineSequence: existing
          ? nextState.nextTimelineSequence
          : nextState.nextTimelineSequence + 1,
        toolCalls: {
          ...nextState.toolCalls,
          [streamEvent.data.tool_call_id]: {
            args: existing?.args,
            name: existing?.name ?? "run_workflow",
            result: existing?.result ?? null,
            status: workflowStatus,
            timelineSequence,
            tool_call_id: streamEvent.data.tool_call_id,
            workflowState: streamEvent.data.state,
            ...(existing?.parentToolCallId === undefined
              ? {}
              : { parentToolCallId: existing.parentToolCallId }),
            ...(streamEvent.data.output_excerpt === undefined
              ? existing?.workflowOutputExcerpt === undefined
                ? {}
                : { workflowOutputExcerpt: existing.workflowOutputExcerpt }
              : { workflowOutputExcerpt: streamEvent.data.output_excerpt }),
            ...(streamEvent.data.error_excerpt === undefined
              ? existing?.workflowErrorExcerpt === undefined
                ? {}
                : { workflowErrorExcerpt: existing.workflowErrorExcerpt }
              : { workflowErrorExcerpt: streamEvent.data.error_excerpt }),
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
  role: "assistant",
  channel: MessageChannel | undefined,
  timelineSequence: number
): ChatMessageDraft[] {
  const nextMessage: ChatMessageDraft = {
    channel: channel ?? "text",
    id: messageId,
    role,
    status: "streaming",
    text: "",
    timelineSequence,
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
  text: string,
  timelineSequence: number
): ChatMessageDraft[] {
  const existingIndex = messages.findIndex((message) => message.id === messageId)
  if (existingIndex === -1) {
    return [
      ...messages,
      {
        channel: "text",
        id: messageId,
        role: "assistant" as const,
        status: "streaming" as const,
        text,
        timelineSequence,
      },
    ]
  }

  return messages.map((message) =>
    message.id === messageId ? { ...message, text: `${message.text}${text}` } : message
  )
}

export function selectLiveTimeline(
  messages: ChatMessageDraft[],
  toolCalls: ToolCallState[]
): LiveTimelineItem[] {
  const timeline: LiveTimelineItem[] = [
    ...messages
      .filter((message) => message.channel === "text")
      .map((message) => ({
        kind: "text" as const,
        message,
        sequence: message.timelineSequence,
      })),
    ...toolCalls
      .filter((toolCall) => !toolCall.parentToolCallId)
      .map((toolCall) => ({
        kind: "tool" as const,
        toolCall,
        sequence: toolCall.timelineSequence,
      })),
  ]

  return timeline.sort((left, right) => left.sequence - right.sequence)
}

export function selectChildToolCalls(
  toolCalls: ToolCallState[],
  parentToolCallId: string
): ToolCallState[] {
  let childrenByParent = childToolCallCache.get(toolCalls)
  if (!childrenByParent) {
    childrenByParent = new Map<string, ToolCallState[]>()
    for (const toolCall of toolCalls) {
      if (!toolCall.parentToolCallId) {
        continue
      }
      const children = childrenByParent.get(toolCall.parentToolCallId) ?? []
      children.push(toolCall)
      childrenByParent.set(toolCall.parentToolCallId, children)
    }
    for (const children of childrenByParent.values()) {
      children.sort((left, right) => left.timelineSequence - right.timelineSequence)
    }
    childToolCallCache.set(toolCalls, childrenByParent)
  }
  return childrenByParent.get(parentToolCallId) ?? EMPTY_TOOL_CALLS
}

const childToolCallCache = new WeakMap<ToolCallState[], Map<string, ToolCallState[]>>()
const EMPTY_TOOL_CALLS: ToolCallState[] = []

function nestedResultStatus(
  result: unknown,
  parentToolCallId: string | undefined
): ToolCallState["status"] {
  if (!parentToolCallId || typeof result !== "object" || result === null || Array.isArray(result)) {
    return "completed"
  }
  const status = (result as Record<string, unknown>)["status"]
  if (status === "failed" || status === "denied") {
    return status
  }
  if (status === "pending") {
    return "awaiting_approval"
  }
  return "completed"
}

function completeMessage(messages: ChatMessageDraft[], messageId: string): ChatMessageDraft[] {
  return messages.map((message) =>
    message.id === messageId ? { ...message, status: "complete" as const } : message
  )
}

function withStreamError(state: AgentStreamState, error: StreamError): AgentStreamState {
  return {
    ...state,
    isConnected: false,
    done: true,
    error,
    status: "failed",
  }
}
