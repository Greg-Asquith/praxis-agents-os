import { describe, expect, it } from "vitest"

import { buildLiveToolActivities } from "@/features/conversations/live-tool-activities"
import { parseConversationMessages } from "@/features/conversations/message-parts"
import type { ApprovalState, ToolCallState } from "@/features/conversations/stream/reducer"
import type { ConversationMessage, PendingWorkflowState } from "@/features/conversations/types"

describe("code-mode live and replay parity", () => {
  it("builds the same normalized activity tree from stream events and persisted trace metadata", () => {
    const live = buildLiveToolActivities(liveToolCalls(), [], null)
    const replay = parseConversationMessages(replayMessages())

    expect(live).toHaveLength(2)
    expect(live[0]).toEqual(replay[0]?.toolActivities[0])
  })

  it("merges approval provenance into an existing live nested tool call", () => {
    const [activity] = buildLiveToolActivities(
      [
        {
          args: { value: "change" },
          name: "write_setting",
          parentToolCallId: "workflow-1",
          result: null,
          status: "awaiting_approval",
          timelineSequence: 1,
          tool_call_id: "workflow-1:1",
        },
      ],
      [taintedApproval()],
      null
    )

    expect(activity).toMatchObject({
      derivedFromUntrusted: true,
      kind: "approval",
      status: "awaiting_approval",
      taintSources: [{ source_kind: "integration", source_ref: "row-1" }],
    })
  })

  it("stamps the run id on reloaded workflow children so the pending approval renders in-slot", () => {
    const [message] = parseConversationMessages(
      suspendedMessages(),
      { id: "run-1", status: "awaiting_approval" },
      [],
      undefined,
      pendingWorkflow()
    )

    const outer = message?.toolActivities[0]
    expect(outer?.script?.children.map((child) => child.agentRunId)).toEqual(["run-1", "run-1"])
    expect(outer?.script?.children[1]).toMatchObject({
      id: "workflow-1:2",
      kind: "approval",
      status: "awaiting_approval",
    })
  })

  it("keeps standalone approvals and does not revert a decided tool status", () => {
    const standalone = buildLiveToolActivities([], [taintedApproval()], null)
    const [decided] = buildLiveToolActivities(
      [
        {
          args: {},
          name: "write_setting",
          result: { status: "done" },
          status: "completed",
          timelineSequence: 1,
          tool_call_id: "workflow-1:1",
        },
      ],
      [taintedApproval()],
      null
    )

    expect(standalone[0]).toMatchObject({ kind: "approval", derivedFromUntrusted: true })
    expect(decided).toMatchObject({ status: "completed", kind: "call" })
  })
})

function pendingWorkflow(): PendingWorkflowState {
  return {
    outer_tool_call_id: "workflow-1",
    code: "await check_report(account='one')\nawait write_setting(value='change')",
    reason: null,
    status: "suspended",
    nested_trace: [
      {
        tool_call_id: "workflow-1:1",
        tool_name: "check_report",
        summary: "Check report",
        status: "succeeded",
        result_excerpt: '{"rows":3}',
        position: 1,
      },
      {
        tool_call_id: "workflow-1:2",
        tool_name: "write_setting",
        summary: "Write setting",
        status: "pending",
        result_excerpt: null,
        position: 2,
      },
    ],
    trace_truncated: false,
    pending: {
      tool_call_id: "workflow-1:2",
      name: "write_setting",
      args: { value: "change" },
      parent_tool_call_id: "workflow-1",
    },
    recovery: null,
  }
}

function suspendedMessages(): ConversationMessage[] {
  return [
    {
      ...message("assistant", 1, [
        {
          args: { code: "await write_setting(value='change')" },
          part_kind: "tool-call",
          tool_call_id: "workflow-1",
          tool_name: "run_workflow",
        },
      ]),
      metadata: { agent_run_id: "run-1" },
    },
  ]
}

function taintedApproval(): ApprovalState {
  return {
    args: { value: "change" },
    derived_from_untrusted: true,
    name: "write_setting",
    status: "pending",
    taint_sources: [{ source_kind: "integration", source_ref: "row-1" }],
    tool_call_id: "workflow-1:1",
  }
}

function liveToolCalls(): ToolCallState[] {
  return [
    {
      args: {
        code: "report = await check_report(account='one')\nreport",
        reason: "Check the account",
      },
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

function replayMessages(): ConversationMessage[] {
  return [
    message("assistant", 1, [
      {
        args: {
          code: "report = await check_report(account='one')\nreport",
          reason: "Check the account",
        },
        part_kind: "tool-call",
        tool_call_id: "workflow-1",
        tool_name: "run_workflow",
      },
    ]),
    message("tool", 2, [
      {
        content: { result: "done" },
        metadata: {
          code_mode_trace: {
            calls: [
              {
                args_sha256: "digest",
                excerpt: '{"rows":3}',
                presentation_result: { rows: 3 },
                order: 1,
                parent_tool_call_id: "workflow-1",
                status: "succeeded",
                summary: "Check report",
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

function message(
  role: string,
  sequence: number,
  parts: Record<string, unknown>[]
): ConversationMessage {
  const timestamp = "2026-08-13T10:00:00.000Z"
  return {
    client_message_id: null,
    conversation_id: "conversation-1",
    created_at: timestamp,
    error: null,
    id: `message-${String(sequence)}`,
    metadata: null,
    parts: { parts },
    role,
    sequence,
    tool_name: null,
    updated_at: timestamp,
  }
}
