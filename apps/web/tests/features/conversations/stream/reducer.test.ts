import { describe, expect, it } from "vitest"

import type { StreamEvent } from "@/features/conversations/stream/protocol"
import {
  agentStreamReducer,
  initialAgentStreamState,
  selectChildToolCalls,
  selectLiveTimeline,
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
          timelineSequence: 0,
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

  it("tracks the stream transport connection", () => {
    const connectedState = agentStreamReducer(initialAgentStreamState, { type: "connect" })

    expect(connectedState.isConnected).toBe(true)
    expect(agentStreamReducer(connectedState, { type: "disconnect" }).isConnected).toBe(false)
  })

  it("tracks a queued turn without marking it terminal", () => {
    const state = reduceEvents([
      {
        event: "run.status",
        data: { ...eventWithSeq(1), status: "queued" },
      },
    ])

    expect(state.status).toBe("queued")
    expect(state.done).toBe(false)
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
        timelineSequence: 0,
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
      timelineSequence: 0,
    })
  })

  it("keeps an early tool row while replacing incomplete arguments", () => {
    const state = reduceEvents([
      {
        event: "tool.call",
        data: {
          ...eventWithSeq(1),
          tool_call_id: "artifact-1",
          name: "create_artifact",
          args: null,
        },
      },
      {
        event: "tool.call",
        data: {
          ...eventWithSeq(2),
          tool_call_id: "artifact-1",
          name: "create_artifact",
          args: { title: "Launch map", content: "<html>…</html>" },
        },
      },
    ])

    expect(Object.keys(state.toolCalls)).toEqual(["artifact-1"])
    expect(state.toolCalls["artifact-1"]).toMatchObject({
      args: { title: "Launch map", content: "<html>…</html>" },
      status: "running",
      timelineSequence: 0,
    })
    expect(state.nextTimelineSequence).toBe(1)
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
          replay_args: { to: "user@example.com", content_ref: "staged/content.txt" },
          delegation,
        },
      },
    ])

    expect(state.status).toBe("awaiting_approval")
    expect(state.approvals["tool-1"]).toEqual({
      tool_call_id: "tool-1",
      name: "send_email",
      args: { to: "user@example.com" },
      replay_args: { to: "user@example.com", content_ref: "staged/content.txt" },
      delegation,
      status: "pending",
    })
    expect(state.toolCalls["tool-1"]).toEqual({
      tool_call_id: "tool-1",
      name: "send_email",
      args: { to: "user@example.com" },
      result: null,
      status: "awaiting_approval",
      timelineSequence: 0,
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

  it("finalizes an aborted run without discarding streamed drafts", () => {
    const runningState = reduceEvents([
      {
        event: "message.delta",
        data: { ...eventWithSeq(1), message_id: "message-1", text: "Partial reply" },
      },
      {
        event: "tool.call",
        data: {
          ...eventWithSeq(2),
          tool_call_id: "tool-1",
          name: "web_search",
          args: { query: "Praxis Agents" },
        },
      },
      {
        event: "run.status",
        data: { ...eventWithSeq(3), status: "running" },
      },
    ])

    const connectedState = agentStreamReducer(runningState, { type: "connect" })
    const abortedState = agentStreamReducer(connectedState, { type: "abort" })

    expect(abortedState.isConnected).toBe(false)
    expect(abortedState.done).toBe(true)
    expect(abortedState.status).toBe("running")
    expect(abortedState.messages).toBe(runningState.messages)
    expect(abortedState.toolCalls).toBe(runningState.toolCalls)
  })

  it("leaves idle and already-finished streams unchanged when aborted", () => {
    expect(agentStreamReducer(initialAgentStreamState, { type: "abort" })).toBe(
      initialAgentStreamState
    )

    const finishedState = reduceEvents([
      {
        event: "done",
        data: { ...eventWithSeq(1), status: "completed" },
      },
    ])

    expect(agentStreamReducer(finishedState, { type: "abort" })).toBe(finishedState)
  })

  it("ignores stream events after an abort", () => {
    const runningState = reduceEvents([
      {
        event: "run.status",
        data: { ...eventWithSeq(1), status: "running" },
      },
    ])
    const abortedState = agentStreamReducer(runningState, { type: "abort" })
    const nextState = agentStreamReducer(abortedState, {
      type: "event",
      event: {
        event: "message.delta",
        data: { ...eventWithSeq(2), message_id: "message-1", text: "Too late" },
      },
    })

    expect(nextState).toBe(abortedState)
  })

  it("keeps text and tool calls in arrival order while updating results in place", () => {
    const beforeResult = reduceEvents([
      {
        event: "message.start",
        data: {
          ...eventWithSeq(1),
          message_id: "text-1",
          role: "assistant",
          channel: "text",
        },
      },
      {
        event: "message.delta",
        data: { ...eventWithSeq(2), message_id: "text-1", text: "Introduction" },
      },
      {
        event: "tool.call",
        data: {
          ...eventWithSeq(3),
          tool_call_id: "tool-1",
          name: "web_search",
          args: { query: "Praxis Agents" },
        },
      },
      {
        event: "message.start",
        data: {
          ...eventWithSeq(4),
          message_id: "text-2",
          role: "assistant",
          channel: "text",
        },
      },
      {
        event: "message.delta",
        data: { ...eventWithSeq(5), message_id: "text-2", text: "Conclusion" },
      },
    ])
    const sequenceBeforeResult = beforeResult.toolCalls["tool-1"]?.timelineSequence
    const afterResult = reduceEvents(
      [
        {
          event: "tool.result",
          data: {
            ...eventWithSeq(6),
            tool_call_id: "tool-1",
            name: "web_search",
            result: { answer: "Found it" },
          },
        },
      ],
      beforeResult
    )

    expect(
      selectLiveTimeline(afterResult.messages, Object.values(afterResult.toolCalls)).map((item) =>
        item.kind === "text" ? `text:${item.message.id}` : `tool:${item.toolCall.tool_call_id}`
      )
    ).toEqual(["text:text-1", "tool:tool-1", "text:text-2"])
    expect(afterResult.toolCalls["tool-1"]?.timelineSequence).toBe(sequenceBeforeResult)
    expect(afterResult.toolCalls["tool-1"]?.status).toBe("completed")
  })

  it("keeps nested workflow calls normalized and out of the top-level timeline", () => {
    const state = reduceEvents([
      {
        event: "tool.call",
        data: {
          ...eventWithSeq(1),
          tool_call_id: "workflow-1",
          name: "run_workflow",
          args: { code: "await read_file(file_id='file-1')" },
        },
      },
      {
        event: "tool.call",
        data: {
          ...eventWithSeq(2),
          tool_call_id: "workflow-1:1",
          parent_tool_call_id: "workflow-1",
          name: "read_file",
          args: { file_id: "file-1" },
        },
      },
      {
        event: "tool.result",
        data: {
          ...eventWithSeq(3),
          tool_call_id: "workflow-1:1",
          parent_tool_call_id: "workflow-1",
          name: "read_file",
          result: { text: "Contents" },
        },
      },
    ])

    expect(Object.keys(state.toolCalls)).toEqual(["workflow-1", "workflow-1:1"])
    expect(selectChildToolCalls(Object.values(state.toolCalls), "workflow-1")).toEqual([
      expect.objectContaining({
        parentToolCallId: "workflow-1",
        status: "completed",
        tool_call_id: "workflow-1:1",
      }),
    ])
    expect(
      selectLiveTimeline([], Object.values(state.toolCalls)).map(
        (item) => item.kind === "tool" && item.toolCall.tool_call_id
      )
    ).toEqual(["workflow-1"])
  })

  it("preserves parent routing when a nested result arrives before its call", () => {
    const state = reduceEvents([
      {
        event: "tool.result",
        data: {
          ...eventWithSeq(1),
          tool_call_id: "workflow-1:1",
          parent_tool_call_id: "workflow-1",
          name: "read_file",
          result: { text: "Contents" },
        },
      },
      {
        event: "tool.call",
        data: {
          ...eventWithSeq(2),
          tool_call_id: "workflow-1",
          name: "run_workflow",
          args: { code: "'done'" },
        },
      },
    ])

    expect(state.toolCalls["workflow-1:1"]?.parentToolCallId).toBe("workflow-1")
    expect(selectChildToolCalls(Object.values(state.toolCalls), "workflow-1")).toHaveLength(1)
  })

  it("routes a nested approval to its workflow even without an earlier call event", () => {
    const state = reduceEvents([
      {
        event: "tool.approval_required",
        data: {
          ...eventWithSeq(1),
          tool_call_id: "workflow-1:3",
          parent_tool_call_id: "workflow-1",
          name: "send_email",
          args: { subject: "Campaign update" },
        },
      },
    ])

    expect(state.toolCalls["workflow-1:3"]).toMatchObject({
      parentToolCallId: "workflow-1",
      status: "awaiting_approval",
    })
    expect(selectLiveTimeline([], Object.values(state.toolCalls))).toEqual([])
  })

  it("uses the nested result envelope to show failed and denied steps accurately", () => {
    const state = reduceEvents([
      {
        event: "tool.result",
        data: {
          ...eventWithSeq(1),
          tool_call_id: "workflow-1:1",
          parent_tool_call_id: "workflow-1",
          name: "read_file",
          result: { status: "failed", error: "File unavailable" },
        },
      },
      {
        event: "tool.result",
        data: {
          ...eventWithSeq(2),
          tool_call_id: "workflow-1:2",
          parent_tool_call_id: "workflow-1",
          name: "send_email",
          result: { status: "denied", error: "Operator declined" },
        },
      },
    ])

    expect(state.toolCalls["workflow-1:1"]?.status).toBe("failed")
    expect(state.toolCalls["workflow-1:2"]?.status).toBe("denied")
  })

  it("tracks workflow state and bounded outcome excerpts on the outer call", () => {
    const state = reduceEvents([
      {
        event: "workflow.state",
        data: { ...eventWithSeq(1), tool_call_id: "workflow-1", state: "started" },
      },
      {
        event: "tool.call",
        data: {
          ...eventWithSeq(2),
          tool_call_id: "workflow-1",
          name: "run_workflow",
          args: { code: "'done'", ignored_future_field: true },
        },
      },
      {
        event: "workflow.state",
        data: {
          ...eventWithSeq(3),
          tool_call_id: "workflow-1",
          state: "completed",
          output_excerpt: "finished",
        },
      },
    ])

    expect(state.toolCalls["workflow-1"]).toMatchObject({
      args: { code: "'done'", ignored_future_field: true },
      status: "completed",
      timelineSequence: 0,
      workflowOutputExcerpt: "finished",
      workflowState: "completed",
    })
  })

  it("marks a failed workflow without discarding its call arguments", () => {
    const state = reduceEvents([
      {
        event: "tool.call",
        data: {
          ...eventWithSeq(1),
          tool_call_id: "workflow-1",
          name: "run_workflow",
          args: { code: "raise ValueError('no')", reason: "Check the report" },
        },
      },
      {
        event: "workflow.state",
        data: {
          ...eventWithSeq(2),
          tool_call_id: "workflow-1",
          state: "failed",
          error_excerpt: "The workflow could not finish.",
        },
      },
    ])

    expect(state.toolCalls["workflow-1"]).toMatchObject({
      args: { code: "raise ValueError('no')", reason: "Check the report" },
      status: "failed",
      workflowErrorExcerpt: "The workflow could not finish.",
      workflowState: "failed",
    })
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
