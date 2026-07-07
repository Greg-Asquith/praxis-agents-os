import { describe, expect, it } from "vitest"

import type { StreamEvent } from "@/features/conversations/stream/protocol"
import {
  agentStreamReducer,
  initialAgentStreamState,
  type AgentStreamState,
} from "@/features/conversations/stream/reducer"
import type { Conversation } from "@/features/conversations/types"

const baseEnvelope = {
  run_id: "run-1",
  conversation_id: "conversation-1",
} as const

const conversation: Conversation = {
  id: "conversation-1",
  user_id: "user-1",
  workspace_id: "workspace-1",
  created_by: "user-1",
  title: "Launch plan",
  description: null,
  status: "active",
  metadata: null,
  unread: false,
  source: "direct",
  last_message_at: null,
  active_agent_id: "agent-1",
  agent_slug: "planner",
  agent_name: "Planner",
  active_run_id: "run-1",
  active_run_status: "running",
  needs_approval: false,
  created_at: "2026-07-06T08:00:00Z",
  updated_at: "2026-07-06T08:00:00Z",
}

function eventWithSeq(seq: number) {
  return { ...baseEnvelope, seq }
}

function reduceEvents(events: StreamEvent[], state = initialAgentStreamState) {
  return events.reduce(
    (currentState, event) => agentStreamReducer(currentState, { type: "event", event }),
    state
  )
}

describe("agentStreamReducer", () => {
  it("resets transient state when a stream starts", () => {
    const dirtyState: AgentStreamState = {
      ...initialAgentStreamState,
      conversationId: "old-conversation",
      runId: "old-run",
      status: "failed",
      messages: [
        {
          channel: "text",
          id: "old-message",
          role: "assistant",
          text: "stale",
          status: "complete",
        },
      ],
      error: { code: "old_error", message: "Old error" },
      done: true,
      lastSeq: 10,
    }

    expect(agentStreamReducer(dirtyState, { type: "start" })).toEqual({
      ...initialAgentStreamState,
      status: "pending",
    })
  })

  it("stores conversation data from create and update events", () => {
    const created = {
      event: "conversation.created",
      data: { ...eventWithSeq(1), conversation },
    } satisfies StreamEvent
    const updatedConversation = { ...conversation, title: "Updated launch plan" }
    const updated = {
      event: "conversation.updated",
      data: { ...eventWithSeq(2), conversation: updatedConversation },
    } satisfies StreamEvent

    const state = reduceEvents([created, updated])

    expect(state.conversation).toEqual(updatedConversation)
    expect(state.conversationId).toBe("conversation-1")
    expect(state.runId).toBe("run-1")
    expect(state.lastSeq).toBe(2)
  })

  it("accumulates assistant message tokens and completes the draft", () => {
    const state = reduceEvents([
      {
        event: "message.start",
        data: {
          ...eventWithSeq(1),
          message_id: "message-1",
          role: "assistant",
          channel: "thinking",
        },
      },
      {
        event: "message.delta",
        data: { ...eventWithSeq(2), message_id: "message-1", text: "Hel" },
      },
      {
        event: "message.delta",
        data: { ...eventWithSeq(3), message_id: "message-1", text: "lo" },
      },
      {
        event: "message.end",
        data: { ...eventWithSeq(4), message_id: "message-1" },
      },
    ])

    expect(state.messages).toEqual([
      {
        channel: "thinking",
        id: "message-1",
        role: "assistant",
        text: "Hello",
        status: "complete",
      },
    ])
  })

  it("pairs tool call arguments with later tool results", () => {
    const state = reduceEvents([
      {
        event: "tool.call",
        data: {
          ...eventWithSeq(1),
          tool_call_id: "tool-1",
          name: "read_file",
          args: { file_id: "file-1" },
        },
      },
      {
        event: "tool.result",
        data: {
          ...eventWithSeq(2),
          tool_call_id: "tool-1",
          name: "read_file",
          result: { text: "Contents" },
        },
      },
    ])

    expect(state.toolCalls["tool-1"]).toEqual({
      tool_call_id: "tool-1",
      name: "read_file",
      args: { file_id: "file-1" },
      result: { text: "Contents" },
      status: "completed",
    })
  })

  it("records approval-required tool state and run status", () => {
    const delegation = {
      parent_tool_call_id: "parent-tool-1",
      child_agent_id: "agent-2",
      child_agent_name: "Researcher",
      child_conversation_id: "conversation-2",
      child_run_id: "run-2",
      pending_approval_count: 1,
    }
    const state = reduceEvents([
      {
        event: "tool.approval_required",
        data: {
          ...eventWithSeq(1),
          tool_call_id: "tool-1",
          name: "send_email",
          args: { to: "user@example.com" },
          delegation,
        },
      },
    ])

    expect(state.status).toBe("awaiting_approval")
    expect(state.approvals["tool-1"]).toEqual({
      tool_call_id: "tool-1",
      name: "send_email",
      args: { to: "user@example.com" },
      delegation,
      status: "pending",
    })
    expect(state.toolCalls["tool-1"]).toEqual({
      tool_call_id: "tool-1",
      name: "send_email",
      args: { to: "user@example.com" },
      result: null,
      status: "awaiting_approval",
    })
  })

  it("marks done events as terminal with the final run status", () => {
    const state = reduceEvents([
      {
        event: "run.status",
        data: { ...eventWithSeq(1), status: "running" },
      },
      {
        event: "done",
        data: { ...eventWithSeq(2), status: "completed" },
      },
    ])

    expect(state.done).toBe(true)
    expect(state.status).toBe("completed")
    expect(state.error).toBeNull()
  })

  it("marks error events as failed and stores the stream error", () => {
    const state = reduceEvents([
      {
        event: "error",
        data: {
          ...eventWithSeq(1),
          code: "provider_failure",
          message: "Provider failed.",
        },
      },
    ])

    expect(state.done).toBe(true)
    expect(state.status).toBe("failed")
    expect(state.error).toEqual({
      code: "provider_failure",
      message: "Provider failed.",
    })
  })
})
