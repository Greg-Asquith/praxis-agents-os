import { describe, expect, it } from "vitest"

import { buildLiveToolActivities } from "@/features/conversations/live-tool-activities"
import { parseConversationMessages } from "@/features/conversations/message-parts"
import type { ToolCallState } from "@/features/conversations/stream/reducer"
import type { ConversationMessage } from "@/features/conversations/types"

describe("code-mode live and replay parity", () => {
  it("builds the same normalized activity tree from stream events and persisted trace metadata", () => {
    const live = buildLiveToolActivities(liveToolCalls(), [], null)
    const replay = parseConversationMessages(replayMessages())

    expect(live).toHaveLength(2)
    expect(live[0]).toEqual(replay[0]?.toolActivities[0])
  })
})

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
