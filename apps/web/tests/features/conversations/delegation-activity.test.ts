// apps/web/tests/features/conversations/delegation-activity.test.ts

import { describe, expect, it } from "vitest"

import { delegateToolActivities } from "@/features/conversations/delegation-activity"
import type { ConversationMessage } from "@/features/conversations/types"

const createdAt = "2026-09-08T20:47:00.000Z"

describe("delegateToolActivities", () => {
  it("pairs the delegate's calls with their results and keeps unfinished calls running", () => {
    const activities = delegateToolActivities(transcript(), true)

    expect(activities.map((activity) => [activity.name, activity.kind, activity.status])).toEqual([
      ["search_gmail", "call", "completed"],
      ["read_gmail", "call", "running"],
    ])
    expect(activities[0]?.result).toEqual({ count: 3 })
  })

  it("marks unfinished calls as unknown once the delegation is over", () => {
    const activities = delegateToolActivities(transcript(), false)

    expect(activities.map((activity) => activity.status)).toEqual(["completed", "unknown"])
  })

  it("returns nothing for a transcript without tool calls", () => {
    expect(
      delegateToolActivities([
        message("m-1", "assistant", 1, [{ part_kind: "text", content: "Done." }]),
      ])
    ).toEqual([])
  })
})

function transcript(): ConversationMessage[] {
  return [
    message("m-1", "user", 1, [{ part_kind: "user-prompt", content: "Summarise the inbox" }]),
    message("m-2", "assistant", 2, [
      { part_kind: "tool-call", tool_call_id: "call-1", tool_name: "search_gmail", args: {} },
    ]),
    message("m-3", "tool", 3, [
      {
        part_kind: "tool-return",
        tool_call_id: "call-1",
        tool_name: "search_gmail",
        content: { count: 3 },
      },
    ]),
    message("m-4", "assistant", 4, [
      { part_kind: "tool-call", tool_call_id: "call-2", tool_name: "read_gmail", args: {} },
    ]),
  ]
}

function message(
  id: string,
  role: string,
  sequence: number,
  parts: Record<string, unknown>[]
): ConversationMessage {
  return {
    id,
    conversation_id: "child-conversation",
    role,
    parts: { parts },
    metadata: { agent_run_id: "child-run" },
    tool_name: null,
    error: null,
    sequence,
    client_message_id: null,
    created_at: createdAt,
    updated_at: createdAt,
  }
}
