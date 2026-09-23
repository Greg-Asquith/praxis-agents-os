import { describe, expect, it } from "vitest"

import {
  projectConversationTimeline,
  type ConversationTimeline,
  type ConversationTimelineInput,
} from "@/features/conversations/message-parts/timeline"
import type { ToolCallState } from "@/features/conversations/stream/reducer"
import type {
  AgentRun,
  ConversationMessage,
  PendingToolApproval,
} from "@/features/conversations/types"

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
    expected: [{ id: "call-1", status: "stopped" }],
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

  it("uses display arguments for a persisted approval row", () => {
    const timeline = projectConversationTimeline(
      input({
        approvals: [
          {
            args: { value: "display value" },
            name: "test_tool",
            tool_call_id: "call-1",
          },
        ],
        messages: [runMessage("message-1", "run-1", [toolCall("call-1")])],
        transcriptRun: { id: "run-1", status: "awaiting_approval" },
      })
    )

    expect(transcriptActivities(timeline)[0]).toMatchObject({
      args: { value: "display value" },
      status: "awaiting_approval",
    })
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
    if (row.kind === "pending-message" || row.kind === "run-outcome") {
      return []
    }
    if (row.kind === "assistant-turn") {
      return row.messages.flatMap((message) => message.toolActivities)
    }
    return row.message.toolActivities
  })
}

it("renders multiple child workflows with independently owned reviewable leaves after reload", () => {
  const workflows = ["child-a", "child-b"].map((owner) => ({
    owner_run_id: owner,
    outer_tool_call_id: "workflow",
    code: "await write_file(name='report.txt')",
    reason: "Save report",
    status: "suspended" as const,
    nested_trace: [
      {
        tool_call_id: "read",
        tool_name: "read_file",
        summary: "Read report",
        status: "succeeded" as const,
        result_excerpt: null,
        presentation_result: { content: "complete report" },
        position: 1,
      },
    ],
    trace_truncated: false,
    recovery: null,
    pending: {
      ...approval("nested"),
      name: "write_file",
      approval_id: `approval-${owner}`,
      owner_run_id: owner,
      parent_tool_call_id: "workflow",
      derived_from_untrusted: true,
      delegation: {
        parent_tool_call_id: `delegate-${owner}`,
        child_run_id: owner,
        child_agent_id: `agent-${owner}`,
        child_agent_name: owner,
        child_conversation_id: `conversation-${owner}`,
        pending_approval_count: 1,
      },
    },
  }))
  const timeline = projectConversationTimeline(
    input({
      transcriptRun: { id: "root", status: "awaiting_approval" },
      approvals: workflows.map((workflow) => workflow.pending),
      pendingWorkflows: workflows,
    })
  )
  expect(timeline.orphanApprovals).toHaveLength(2)
  expect(timeline.orphanApprovals.map((activity) => activity.delegate?.agentName)).toEqual([
    "child-a",
    "child-b",
  ])
  for (const [index, owner] of ["child-a", "child-b"].entries()) {
    expect(timeline.orphanApprovals[index]?.script?.children.at(-1)).toMatchObject({
      id: "nested",
      agentRunId: owner,
      rootRunId: "root",
      approvalId: `approval-${owner}`,
      name: "write_file",
      args: { value: "input" },
      derivedFromUntrusted: true,
    })
  }
  expect(timeline.orphanApprovals[0]?.script?.children[0]?.result).toEqual({
    content: "complete report",
  })
})

function failedRun(id: string, overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id,
    conversation_id: "conversation-1",
    agent_id: "agent-1",
    workspace_id: "workspace-1",
    user_id: "user-1",
    parent_run_id: null,
    delegation_depth: 0,
    trigger: "interactive",
    status: "failed",
    outcome: "error",
    model_name: null,
    started_at: createdAt,
    completed_at: null,
    failed_at: createdAt,
    lease_expires_at: null,
    error_code: "provider_error",
    error_message: "The model could not finish this run.",
    completion_json: null,
    created_at: createdAt,
    updated_at: createdAt,
    ...overrides,
  }
}

function runText(id: string, runId: string) {
  return runMessage(id, runId, [{ part_kind: "text", content: id }])
}

describe("persisted run failure notices", () => {
  it("places one reason after each failed run, including older runs with identical errors", () => {
    const runs = {
      first: failedRun("first"),
      second: failedRun("second"),
      done: failedRun("done", { status: "completed" }),
    }
    const timeline = projectConversationTimeline(
      input({
        runs,
        messages: [
          runText("first-part", "first"),
          runText("last-part", "first"),
          runText("second-part", "second"),
          runText("done-part", "done"),
        ],
      })
    )
    expect(timeline.rows.map((row) => row.kind)).toEqual([
      "assistant-turn",
      "run-outcome",
      "assistant-turn",
      "run-outcome",
      "assistant-turn",
    ])
    expect(timeline.rows.filter((row) => row.kind === "run-outcome")).toMatchObject([
      { agentRunId: "first", outcome: { message: runs.first.error_message } },
      { agentRunId: "second", outcome: { message: runs.second.error_message } },
    ])
  })

  it("shows a failure after the user prompt when no assistant response was saved", () => {
    const prompt = {
      ...message("prompt", "user", 1, [{ part_kind: "user-prompt", content: "Hello" }]),
      metadata: { agent_run_id: "failed" },
    }
    const timeline = projectConversationTimeline(
      input({ runs: { failed: failedRun("failed") }, messages: [prompt] })
    )
    expect(timeline.rows.map((row) => row.kind)).toEqual(["message", "run-outcome"])
  })

  it("rebuilds budget copy at an older run boundary", () => {
    const run = failedRun("budget", {
      outcome: "budget_exhausted",
      completion_json: {
        tripped_budget: { kind: "total_tokens", limit: 1000000 },
        observed_total_tokens: 1100000,
        requests: 12,
      },
    })
    const timeline = projectConversationTimeline(
      input({ runs: { budget: run }, messages: [runText("reply", "budget")] })
    )
    const notice = timeline.rows.at(-1)
    expect(notice?.kind).toBe("run-outcome")
    if (notice?.kind !== "run-outcome") throw new Error("Expected run failure notice")
    expect(notice.outcome.title).toBe("Run limit reached")
    expect(notice.outcome.message).toContain("1,100,000 tokens across 12 requests")
  })

  it("suppresses only the run with a visible live error or recovery banner, then restores it on reload", () => {
    const base = input({
      runs: { old: failedRun("old"), live: failedRun("live") },
      messages: [runText("old-reply", "old"), runText("live-reply", "live")],
      visibleRunNoticeIds: ["live"],
    })
    expect(
      projectConversationTimeline(base)
        .rows.filter((row) => row.kind === "run-outcome")
        .map((row) => row.agentRunId)
    ).toEqual(["old"])
    expect(
      projectConversationTimeline({ ...base, visibleRunNoticeIds: [] })
        .rows.filter((row) => row.kind === "run-outcome")
        .map((row) => row.agentRunId)
    ).toEqual(["old", "live"])
  })

  it.each(["completed", "cancelled", "running", "awaiting_approval"] as const)(
    "adds no failure notice for a %s run or an unreferenced run",
    (status) => {
      const timeline = projectConversationTimeline(
        input({
          runs: { visible: failedRun("visible", { status }), missing: failedRun("missing") },
          messages: [runText("reply", "visible"), runText("no-record", "unknown")],
        })
      )
      expect(timeline.rows.every((row) => row.kind !== "run-outcome")).toBe(true)
    }
  )
})
