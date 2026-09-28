import { describe, expect, it } from "vitest"

import type { StreamEvent } from "@/features/conversations/stream/protocol"
import {
  agentStreamReducer,
  initialAgentStreamState,
  selectChildToolCalls,
  selectLiveTimeline,
  type AgentStreamState,
} from "@/features/conversations/stream/reducer"
import { approvalIdentity } from "../../../support/approvals"

const baseEnvelope = {
  run_id: "run-1",
  conversation_id: "conversation-1",
} as const

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
          ...approvalIdentity("tool-1", "run-2", "run-1"),
          approval_revision: "a".repeat(64),
          tool_call_id: "tool-1",
          name: "send_email",
          args: { to: "user@example.com" },
          replay_args: { to: "user@example.com", content_ref: "staged/content.txt" },
          delegation,
        },
      },
    ])

    expect(state.status).toBe("awaiting_approval")
    expect(Object.values(state.approvals)[0]).toEqual({
      ...approvalIdentity("tool-1", "run-2", "run-1"),
      tool_call_id: "tool-1",
      name: "send_email",
      args: { to: "user@example.com" },
      replay_args: { to: "user@example.com", content_ref: "staged/content.txt" },
      delegation,
      status: "pending",
    })
    expect(Object.values(state.toolCalls)[0]).toEqual({
      approval_id: "tool-1",
      owner_run_id: "run-2",
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
          ...approvalIdentity("workflow-1:3"),
          approval_revision: "a".repeat(64),
          tool_call_id: "workflow-1:3",
          parent_tool_call_id: "workflow-1",
          name: "send_email",
          args: { subject: "Campaign update" },
        },
      },
    ])

    expect(state.toolCalls[JSON.stringify(["run-1", "workflow-1:3"])]).toMatchObject({
      parentToolCallId: "workflow-1",
      status: "awaiting_approval",
    })
    expect(selectLiveTimeline([], Object.values(state.toolCalls))).toEqual([])
  })

  it("uses the streamed outcome for top-level failed and denied tools", () => {
    const state = reduceEvents([
      {
        event: "tool.result",
        data: {
          ...eventWithSeq(1),
          tool_call_id: "denied-1",
          name: "gmail_send_message",
          result: "The user declined this action.",
          outcome: "denied",
          reason: "The budget is too high.",
        },
      },
      {
        event: "tool.result",
        data: {
          ...eventWithSeq(2),
          tool_call_id: "failed-1",
          name: "read_file",
          result: "File unavailable",
          outcome: "failed",
        },
      },
    ])

    expect(state.toolCalls["denied-1"]?.status).toBe("denied")
    expect(state.toolCalls["denied-1"]?.decisionReason).toBe("The budget is too high.")
    expect(state.toolCalls["failed-1"]?.status).toBe("failed")
  })

  it("marks a retry returned to the model as failed rather than completed", () => {
    const state = reduceEvents([
      {
        event: "tool.result",
        data: {
          ...eventWithSeq(1),
          tool_call_id: "retry-1",
          name: "google_ads_list_report_fields",
          result: "Google Ads has no report resource named auction_insight.",
          outcome: "retry",
        },
      },
    ])

    expect(state.toolCalls["retry-1"]?.status).toBe("failed")
    expect(state.toolCalls["retry-1"]?.result).toBe(
      "Google Ads has no report resource named auction_insight."
    )
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

it("retains distinct owner calls and opaque approvals with colliding native IDs", () => {
  const state = reduceEvents(
    ["child-a", "child-b", "run-1"].map((owner, index) => ({
      event: "tool.approval_required" as const,
      data: {
        ...eventWithSeq(index + 1),
        owner_run_id: owner,
        approval_id: `approval-${owner}`,
        approval_revision: "round-1",
        root_run_id: "run-1",
        tool_call_id: "same",
        name: "write_file",
        args: { name: owner },
      },
    }))
  )
  expect(Object.values(state.toolCalls).map((call) => call.owner_run_id)).toEqual([
    "child-a",
    "child-b",
    "run-1",
  ])
  expect(Object.keys(state.approvals)).toEqual([
    "approval-child-a",
    "approval-child-b",
    "approval-run-1",
  ])
  expect(Object.values(state.approvals).every((approval) => approval.tool_call_id === "same")).toBe(
    true
  )
  expect(state.approvalRevision).toBe("round-1")
})
