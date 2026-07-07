import { describe, expect, it } from "vitest"

import { parseConversationMessages } from "@/features/conversations/message-parts/parse"
import type {
  AgentRunStatus,
  ConversationMessage,
  PendingDelegatedApproval,
} from "@/features/conversations/types"

const createdAt = "2026-07-07T10:00:00.000Z"

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
        message("message-1", "assistant", 1, [
          {
            part_kind: "tool-call",
            tool_call_id: "delegate-1",
            tool_name: "delegate_to_agent",
            args: { agent_id: "agent-2", task: "Check approvals" },
          },
        ]),
      ],
      "awaiting_approval",
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

    const parsed = parseConversationMessages(messages, "completed" satisfies AgentRunStatus)

    expect(parsed.map((item) => item.id)).toEqual(["message-2", "message-1"])
    expect(parsed.map((item) => item.sequence)).toEqual([2, 1])
  })
})
