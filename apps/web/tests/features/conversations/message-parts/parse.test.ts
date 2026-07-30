import { describe, expect, it } from "vitest"

import {
  parseConversationMessages,
  toolActivityIdentity,
} from "@/features/conversations/message-parts"
import type {
  AgentRun,
  AgentRunStatus,
  ConversationMessage,
  PendingDelegatedApproval,
} from "@/features/conversations/types"

const createdAt = "2026-07-07T10:00:00.000Z"
const run = (id: string, status: AgentRunStatus): Pick<AgentRun, "id" | "status"> => ({
  id,
  status,
})

function message(
  id: string,
  role: string,
  sequence: number,
  parts: Record<string, unknown>[],
  metadata: Record<string, unknown> | null = null
): ConversationMessage {
  return {
    id,
    conversation_id: "conversation-1",
    role,
    parts: { parts },
    metadata,
    tool_name: null,
    error: null,
    sequence,
    client_message_id: null,
    created_at: createdAt,
    updated_at: createdAt,
  }
}

describe("parseConversationMessages", () => {
  it("marks an unresolved tool call as failed when its run failed", () => {
    const parsed = parseConversationMessages(
      [
        message(
          "message-1",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "send-1",
              tool_name: "gmail_send_message",
              args: { to: ["client@example.com"], subject: "Update", body_text: "Hello" },
            },
          ],
          { agent_run_id: "run-1" }
        ),
      ],
      run("run-1", "failed")
    )

    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      id: "send-1",
      status: "failed",
    })
  })

  it("preserves thinking and visible parts in source order", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        { part_kind: "thinking", content: "Hidden reasoning" },
        { part_kind: "text", content: "First, I will check." },
        {
          part_kind: "tool-call",
          tool_call_id: "tool-call-1",
          tool_name: "web_search",
          args: { query: "Praxis Agents" },
        },
        {
          part_kind: "tool-return",
          tool_call_id: "tool-call-1",
          tool_name: "web_search",
          outcome: "success",
          content: { answer: "Found it" },
        },
        { part_kind: "text", content: "Here is the conclusion." },
      ]),
    ])

    expect(parsed[0]?.parts).toMatchObject([
      { kind: "thinking", content: "Hidden reasoning" },
      { kind: "text", content: "First, I will check." },
      { kind: "tool", activity: { id: "tool-call-1", status: "completed" } },
      { kind: "text", content: "Here is the conclusion." },
    ])
  })

  it("marks messages without an ordered parts array for grouped fallback rendering", () => {
    const fallbackMessage = message("message-1", "assistant", 1, [])
    fallbackMessage.parts = { content: "Legacy answer" }

    const parsed = parseConversationMessages([fallbackMessage])

    expect(parsed[0]).toMatchObject({ parts: null, text: ["Legacy answer"] })
  })

  it("parses a plain user and assistant exchange", () => {
    const parsed = parseConversationMessages([
      message("message-1", "user", 1, [{ part_kind: "user-prompt", content: "Hello" }]),
      message("message-2", "assistant", 2, [{ part_kind: "text", content: "How can I help?" }]),
    ])

    expect(parsed).toHaveLength(2)
    expect(parsed[0]).toMatchObject({
      id: "message-1",
      role: "user",
      sequence: 1,
      text: ["Hello"],
      toolActivities: [],
      unsupportedParts: [],
    })
    expect(parsed[1]).toMatchObject({
      id: "message-2",
      role: "assistant",
      sequence: 2,
      text: ["How can I help?"],
      toolActivities: [],
      unsupportedParts: [],
    })
  })

  it("pairs a tool call with its result and removes the standalone result row", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        {
          part_kind: "tool-call",
          tool_call_id: "tool-call-1",
          tool_name: "read_file",
          args: { file_id: "file-1" },
        },
      ]),
      message("message-2", "tool", 2, [
        {
          part_kind: "tool-return",
          tool_call_id: "tool-call-1",
          tool_name: "read_file",
          outcome: "success",
          content: { text: "File contents" },
        },
      ]),
    ])

    expect(parsed).toHaveLength(1)
    expect(parsed[0]?.toolActivities).toEqual([
      {
        id: "tool-call-1",
        agentRunId: null,
        kind: "call",
        status: "completed",
        name: "read_file",
        args: { file_id: "file-1" },
        outcome: "success",
        result: { text: "File contents" },
      },
    ])
  })

  it("preserves capability-load metadata for skill activation rows", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        {
          part_kind: "tool-call",
          tool_call_id: "tool-call-1",
          tool_kind: "capability-load",
          tool_name: "load_capability",
          args: '{"id":"skill:skill-1"}',
        },
        {
          part_kind: "tool-return",
          tool_call_id: "tool-call-1",
          tool_kind: "capability-load",
          tool_name: "load_capability",
          outcome: "success",
          content: { loaded: true },
        },
      ]),
    ])

    expect(parsed).toHaveLength(1)
    expect(parsed[0]?.toolActivities).toEqual([
      {
        id: "tool-call-1",
        agentRunId: null,
        kind: "call",
        status: "completed",
        name: "load_capability",
        args: { id: "skill:skill-1" },
        outcome: "success",
        result: { loaded: true },
        toolKind: "capability-load",
      },
    ])
  })

  it("groups delegation call and return details under one activity", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        {
          part_kind: "tool-call",
          tool_call_id: "delegate-1",
          tool_name: "delegate_to_agent",
          args: {
            agent_id: "agent-2",
            task: "Research the launch plan",
          },
        },
      ]),
      message("message-2", "tool", 2, [
        {
          part_kind: "tool-return",
          tool_call_id: "delegate-1",
          tool_name: "delegate_to_agent",
          outcome: "success",
          content: {
            agent_id: "agent-2",
            agent_name: "Researcher",
            conversation_id: "conversation-2",
            output: "Research complete",
            pending_approvals: [],
            run_id: "run-2",
            status: "completed",
          },
        },
      ]),
    ])

    expect(parsed).toHaveLength(1)
    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      id: "delegate-1",
      kind: "call",
      status: "completed",
      name: "delegate_to_agent",
      delegate: {
        agentId: "agent-2",
        agentName: "Researcher",
        conversationId: "conversation-2",
        output: "Research complete",
        pendingApprovalCount: 0,
        runId: "run-2",
        status: "completed",
        taskPreview: "Research the launch plan",
        truncated: false,
      },
    })
  })

  it("merges pending delegated approvals into a running delegation call", () => {
    const delegations: PendingDelegatedApproval[] = [
      {
        parent_tool_call_id: "delegate-1",
        child_agent_id: "agent-2",
        child_agent_name: "Researcher",
        child_conversation_id: "conversation-2",
        child_run_id: "run-2",
        pending_approval_count: 2,
      },
    ]

    const parsed = parseConversationMessages(
      [
        message(
          "message-1",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "delegate-1",
              tool_name: "delegate_to_agent",
              args: { agent_id: "agent-2", task: "Check approvals" },
            },
          ],
          { agent_run_id: "run-1" }
        ),
      ],
      run("run-1", "awaiting_approval"),
      delegations
    )

    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      kind: "approval",
      status: "awaiting_approval",
      delegate: {
        agentId: "agent-2",
        agentName: "Researcher",
        conversationId: "conversation-2",
        pendingApprovalCount: 2,
        runId: "run-2",
        status: "awaiting_approval",
        taskPreview: "Check approvals",
      },
    })
  })

  it("only marks an unresolved call from the active run as awaiting approval", () => {
    const parsed = parseConversationMessages(
      [
        message(
          "message-old",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "reused-call",
              tool_name: "write_file",
              args: { name: "old.txt" },
            },
          ],
          { agent_run_id: "run-old" }
        ),
        message(
          "message-active",
          "assistant",
          2,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "reused-call",
              tool_name: "write_file",
              args: { name: "active.txt" },
            },
          ],
          { agent_run_id: "run-active" }
        ),
      ],
      run("run-active", "awaiting_approval")
    )

    expect(parsed.map((item) => item.toolActivities[0])).toMatchObject([
      {
        agentRunId: "run-old",
        args: { name: "old.txt" },
        kind: "call",
        status: "unknown",
      },
      {
        agentRunId: "run-active",
        args: { name: "active.txt" },
        kind: "approval",
        status: "awaiting_approval",
      },
    ])
  })

  it("keeps unknown parts as unsupported renderable content", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        { part_kind: "strange-part", content: { value: "unhandled" } },
      ]),
    ])

    expect(parsed).toHaveLength(1)
    expect(parsed[0]?.text).toEqual([])
    expect(parsed[0]?.toolActivities).toEqual([])
    expect(parsed[0]?.unsupportedParts).toHaveLength(1)
    expect(parsed[0]?.unsupportedParts[0]).toMatchObject({
      id: "message-1:0",
      label: "Strange Part",
    })
    expect(parsed[0]?.unsupportedParts[0]?.preview).toContain("unhandled")
  })

  it("preserves input ordering and sequence values for identical timestamps", () => {
    const messages = [
      message("message-2", "assistant", 2, [{ part_kind: "text", content: "Second" }]),
      message("message-1", "assistant", 1, [{ part_kind: "text", content: "First" }]),
    ]

    const parsed = parseConversationMessages(messages, run("run-1", "completed"))

    expect(parsed.map((item) => item.id)).toEqual(["message-2", "message-1"])
    expect(parsed.map((item) => item.sequence)).toEqual([2, 1])
  })

  it("completes a persisted call from a live stream result before persistence catches up", () => {
    const parsed = parseConversationMessages(
      [
        message(
          "message-1",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "tool-call-1",
              tool_name: "gmail_send_message",
              args: { to: ["a@example.com"] },
            },
          ],
          { agent_run_id: "run-1" }
        ),
      ],
      run("run-1", "running"),
      [],
      new Map([[toolActivityIdentity("run-1", "tool-call-1"), { result: { results: [] } }]])
    )

    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      id: "tool-call-1",
      status: "completed",
      result: { results: [] },
    })
  })

  it("keeps a call running when no live result exists for it", () => {
    const parsed = parseConversationMessages(
      [
        message(
          "message-1",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "tool-call-1",
              tool_name: "gmail_send_message",
              args: {},
            },
          ],
          { agent_run_id: "run-1" }
        ),
      ],
      run("run-1", "running"),
      [],
      new Map([[toolActivityIdentity("run-1", "other-call"), { result: "done" }]])
    )

    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      id: "tool-call-1",
      status: "running",
    })
  })

  it("only merges a live result into the matching run when a call id is reused", () => {
    const parsed = parseConversationMessages(
      [
        message(
          "message-old",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "reused-call",
              tool_name: "web_search",
              args: { query: "old" },
            },
          ],
          { agent_run_id: "run-old" }
        ),
        message(
          "message-active",
          "assistant",
          2,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "reused-call",
              tool_name: "web_search",
              args: { query: "active" },
            },
          ],
          { agent_run_id: "run-active" }
        ),
      ],
      run("run-active", "running"),
      [],
      new Map([
        [
          toolActivityIdentity("run-active", "reused-call"),
          { result: { answer: "active result" } },
        ],
      ])
    )

    expect(parsed.map((item) => item.toolActivities[0])).toMatchObject([
      {
        agentRunId: "run-old",
        args: { query: "old" },
        status: "unknown",
      },
      {
        agentRunId: "run-active",
        args: { query: "active" },
        result: { answer: "active result" },
        status: "completed",
      },
    ])
  })
})
