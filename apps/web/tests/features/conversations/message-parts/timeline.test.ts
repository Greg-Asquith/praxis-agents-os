import { describe, expect, it } from "vitest"

import {
  projectConversationTimeline,
  type ConversationTimeline,
  type ConversationTimelineInput,
} from "@/features/conversations/message-parts/timeline"
import type { ToolCallState } from "@/features/conversations/stream/reducer"
import type { ConversationMessage, PendingToolApproval } from "@/features/conversations/types"

const createdAt = "2026-08-21T10:00:00.000Z"
const normalizedWorkflow = {
  id: "workflow-1",
  name: "run_workflow",
  result: { result: "done" },
  script: {
    children: [
      {
        id: "workflow-1:1",
        name: "check_report",
        result: { rows: 3 },
        status: "completed",
      },
    ],
    status: "completed",
  },
  status: "completed",
}

type TimelineScenario = {
  expected: object | null
  input: ConversationTimelineInput
  name: string
  select: (timeline: ConversationTimeline) => unknown
}

const scenarios: TimelineScenario[] = [
  {
    name: "pairs persisted tool results into one transcript row",
    input: input({
      messages: [
        message("assistant-call", "assistant", 1, [toolCall("call-1")]),
        message("tool-result", "tool", 2, [toolResult("call-1", { value: "done" })]),
      ],
    }),
    select: (timeline) => transcriptActivities(timeline),
    expected: [{ id: "call-1", result: { value: "done" }, status: "completed" }],
  },
  {
    name: "heals an unanswered tool call from a terminated run",
    input: input({
      messages: [runMessage("assistant-call", "run-1", [toolCall("call-1")])],
      transcriptRun: { id: "run-1", status: "failed" },
    }),
    select: (timeline) => transcriptActivities(timeline),
    expected: [{ id: "call-1", status: "failed" }],
  },
  {
    name: "uses a completed live result until persistence catches up",
    input: input({
      messages: [runMessage("assistant-call", "run-1", [toolCall("call-1")])],
      stream: stream({ runId: "run-1", toolCalls: [liveToolCall("call-1", "completed")] }),
      transcriptRun: { id: "run-1", status: "running" },
    }),
    select: (timeline) => transcriptActivities(timeline),
    expected: [{ id: "call-1", result: { value: "live" }, status: "completed" }],
  },
  {
    name: "does not use an awaiting-approval live result to settle a transcript call",
    input: input({
      messages: [runMessage("assistant-call", "run-1", [toolCall("call-1")])],
      stream: stream({
        runId: "run-1",
        toolCalls: [liveToolCall("call-1", "awaiting_approval")],
      }),
      transcriptRun: { id: "run-1", status: "running" },
    }),
    select: (timeline) => transcriptActivities(timeline),
    expected: [{ id: "call-1", status: "running" }],
  },
  {
    name: "suppresses a live tool row already present in the same run transcript",
    input: input({
      messages: [runMessage("assistant-call", "run-1", [toolCall("call-1")])],
      stream: stream({ runId: "run-1", toolCalls: [liveToolCall("call-1", "running")] }),
      transcriptRun: { id: "run-1", status: "running" },
    }),
    select: (timeline) => timeline.liveActivity?.timeline,
    expected: [],
  },
  {
    name: "keeps the same call id visible when it belongs to another run",
    input: input({
      messages: [runMessage("assistant-call", "run-1", [toolCall("call-1")])],
      stream: stream({ runId: "run-2", toolCalls: [liveToolCall("call-1", "running")] }),
      transcriptRun: { id: "run-1", status: "running" },
    }),
    select: (timeline) => timeline.liveActivity?.timeline,
    expected: [{ kind: "tool", activity: { agentRunId: "run-2", id: "call-1" } }],
  },
  {
    name: "projects an approval without a transcript call as an orphan",
    input: input({
      approvals: [approval("call-1")],
      transcriptRun: { id: "run-1", status: "awaiting_approval" },
    }),
    select: (timeline) => timeline.orphanApprovals,
    expected: [{ agentRunId: "run-1", id: "call-1", status: "awaiting_approval" }],
  },
  {
    name: "keeps a persisted approval in its transcript tool row",
    input: input({
      approvals: [approval("call-1")],
      messages: [runMessage("assistant-call", "run-1", [toolCall("call-1")])],
      transcriptRun: { id: "run-1", status: "awaiting_approval" },
    }),
    select: (timeline) => ({
      activities: transcriptActivities(timeline),
      orphans: timeline.orphanApprovals,
    }),
    expected: {
      activities: [{ id: "call-1", status: "awaiting_approval" }],
      orphans: [],
    },
  },
  {
    name: "keeps a nested live approval in its workflow row",
    input: input({
      approvals: [approval("workflow-1:1")],
      stream: stream({
        approvals: [
          {
            args: { value: "input" },
            name: "test_tool",
            status: "pending",
            tool_call_id: "workflow-1:1",
          },
        ],
        runId: "run-1",
        toolCalls: [
          {
            ...liveToolCall("workflow-1", "awaiting_approval"),
            args: { code: "await test_tool(value='input')" },
            name: "run_workflow",
          },
          {
            ...liveToolCall("workflow-1:1", "awaiting_approval"),
            parentToolCallId: "workflow-1",
          },
        ],
      }),
      transcriptRun: { id: "run-1", status: "awaiting_approval" },
    }),
    select: (timeline) => timeline.orphanApprovals,
    expected: [],
  },
  {
    name: "normalizes a live Code Mode workflow",
    input: input({ stream: stream({ runId: null, toolCalls: liveWorkflowToolCalls() }) }),
    select: (timeline) => {
      const part = timeline.liveActivity?.timeline[0]
      return part?.kind === "tool" ? part.activity : null
    },
    expected: normalizedWorkflow,
  },
  {
    name: "normalizes a replayed Code Mode workflow to the same shape",
    input: input({ messages: replayWorkflowMessages() }),
    select: (timeline) => transcriptActivities(timeline)[0],
    expected: normalizedWorkflow,
  },
  {
    name: "removes an optimistic message when its persisted copy appears",
    input: input({
      messages: [
        {
          ...message("user-message", "user", 1, [{ content: "Hello", part_kind: "user-prompt" }]),
          client_message_id: "client-1",
        },
      ],
      pendingUserMessages: [pendingMessage("client-1")],
    }),
    select: (timeline) => timeline.rows.map((row) => row.kind),
    expected: ["message"],
  },
  {
    name: "appends a new optimistic message after persisted rows",
    input: input({
      messages: [
        message("assistant-message", "assistant", 1, [{ content: "Hi", part_kind: "text" }]),
      ],
      pendingUserMessages: [pendingMessage("client-2")],
    }),
    select: (timeline) => timeline.rows.map((row) => row.kind),
    expected: ["message", "pending-message"],
  },
  {
    name: "ignores live activity for another conversation",
    input: input({
      stream: stream({
        conversationId: "conversation-2",
        toolCalls: [liveToolCall("call-1", "running")],
      }),
    }),
    select: (timeline) => timeline.liveActivity,
    expected: null,
  },
]

describe("projectConversationTimeline", () => {
  it.each(scenarios)("$name", ({ expected, input: scenarioInput, select }) => {
    const actual = select(projectConversationTimeline(scenarioInput))
    if (expected === null) {
      expect(actual).toBeNull()
      return
    }
    expect(actual).toMatchObject(expected)
  })
})

function input(overrides: Partial<ConversationTimelineInput> = {}): ConversationTimelineInput {
  return {
    approvals: [],
    assistantAgentId: "agent-1",
    conversationId: "conversation-1",
    messages: [],
    pendingDelegations: [],
    pendingUserMessages: [],
    pendingWorkflow: null,
    stream: stream(),
    transcriptRun: null,
    ...overrides,
  }
}

function stream(
  overrides: Partial<ConversationTimelineInput["stream"]> = {}
): ConversationTimelineInput["stream"] {
  return {
    approvals: [],
    conversationId: "conversation-1",
    isStreaming: false,
    messages: [],
    runId: null,
    toolCalls: [],
    ...overrides,
  }
}

function message(
  id: string,
  role: string,
  sequence: number,
  parts: Record<string, unknown>[]
): ConversationMessage {
  return {
    client_message_id: null,
    conversation_id: "conversation-1",
    created_at: createdAt,
    error: null,
    id,
    metadata: null,
    parts: { parts },
    role,
    sequence,
    tool_name: null,
    updated_at: createdAt,
  }
}

function runMessage(id: string, runId: string, parts: Record<string, unknown>[]) {
  return { ...message(id, "assistant", 1, parts), metadata: { agent_run_id: runId } }
}

function toolCall(toolCallId: string) {
  return {
    args: { value: "input" },
    part_kind: "tool-call",
    tool_call_id: toolCallId,
    tool_name: "test_tool",
  }
}

function toolResult(toolCallId: string, content: unknown) {
  return {
    content,
    outcome: "success",
    part_kind: "tool-return",
    tool_call_id: toolCallId,
    tool_name: "test_tool",
  }
}

function liveToolCall(toolCallId: string, status: ToolCallState["status"]): ToolCallState {
  return {
    args: { value: "input" },
    name: "test_tool",
    result: { value: "live" },
    status,
    timelineSequence: 0,
    tool_call_id: toolCallId,
  }
}

function liveWorkflowToolCalls(): ToolCallState[] {
  return [
    {
      args: { code: "report = await check_report(account='one')\nreport" },
      name: "run_workflow",
      result: { result: "done" },
      status: "completed",
      timelineSequence: 0,
      tool_call_id: "workflow-1",
      workflowState: "completed",
    },
    {
      args: { account: "one" },
      name: "check_report",
      parentToolCallId: "workflow-1",
      result: { rows: 3 },
      status: "completed",
      timelineSequence: 1,
      tool_call_id: "workflow-1:1",
    },
  ]
}

function replayWorkflowMessages(): ConversationMessage[] {
  return [
    message("workflow-call", "assistant", 1, [
      {
        args: { code: "report = await check_report(account='one')\nreport" },
        part_kind: "tool-call",
        tool_call_id: "workflow-1",
        tool_name: "run_workflow",
      },
    ]),
    message("workflow-result", "tool", 2, [
      {
        content: { result: "done" },
        metadata: {
          code_mode_trace: {
            calls: [
              {
                excerpt: '{"rows":3}',
                presentation_result: { rows: 3 },
                status: "succeeded",
                tool_call_id: "workflow-1:1",
                tool_name: "check_report",
              },
            ],
          },
        },
        outcome: "success",
        part_kind: "tool-return",
        tool_call_id: "workflow-1",
        tool_name: "run_workflow",
      },
    ]),
  ]
}

function approval(toolCallId: string): PendingToolApproval {
  return { args: { value: "input" }, name: "test_tool", tool_call_id: toolCallId }
}

function pendingMessage(clientMessageId: string) {
  return {
    clientMessageId,
    conversationId: "conversation-1",
    createdAt,
    text: "Hello",
  }
}

function transcriptActivities(timeline: ConversationTimeline) {
  return timeline.rows.flatMap((row) => {
    if (row.kind === "pending-message") {
      return []
    }
    if (row.kind === "assistant-turn") {
      return row.messages.flatMap((message) => message.toolActivities)
    }
    return row.message.toolActivities
  })
}
