import { describe, expect, it } from "vitest"

import {
  pairToolResults,
  toolActivityKey,
} from "@/features/conversations/message-parts/pair-tool-results"
import type { ParsedConversationMessage } from "@/features/conversations/message-parts/types"

function parsedMessage(
  id: string,
  toolActivities: ParsedConversationMessage["toolActivities"]
): ParsedConversationMessage {
  return {
    id,
    role: "assistant",
    sequence: 1,
    agentRunId: null,
    clientMessageId: null,
    createdAt: "2026-07-07T10:00:00.000Z",
    text: [],
    thinking: [],
    attachments: [],
    toolActivities,
    unsupportedParts: [],
  }
}

describe("pairToolResults", () => {
  it("pairs later results with earlier calls by call id", () => {
    const result = {
      id: "tool-1",
      kind: "result" as const,
      status: "completed" as const,
      name: "read_file",
      result: { text: "done" },
    }
    const paired = pairToolResults([
      parsedMessage("message-1", [
        {
          id: "tool-1",
          kind: "call",
          status: "running",
          name: "read_file",
          args: { file_id: "file-1" },
        },
      ]),
      parsedMessage("message-2", [result]),
    ])

    expect(paired.resultsByCallKey.get(toolActivityKey(0, 0))).toBe(result)
    expect(paired.consumedResultKeys.has(toolActivityKey(1, 0))).toBe(true)
  })

  it("leaves orphan calls unpaired", () => {
    const paired = pairToolResults([
      parsedMessage("message-1", [
        {
          id: "tool-1",
          kind: "call",
          status: "running",
          name: "read_file",
        },
      ]),
    ])

    expect(paired.resultsByCallKey.size).toBe(0)
    expect(paired.consumedResultKeys.size).toBe(0)
  })

  it("leaves unpaired results visible", () => {
    const paired = pairToolResults([
      parsedMessage("message-1", [
        {
          id: "tool-1",
          kind: "result",
          status: "completed",
          name: "read_file",
          result: { text: "orphan" },
        },
      ]),
    ])

    expect(paired.resultsByCallKey.size).toBe(0)
    expect(paired.consumedResultKeys.size).toBe(0)
  })

  it("pairs repeated ids with the most recent pending call", () => {
    const paired = pairToolResults([
      parsedMessage("message-1", [
        {
          id: "tool-1",
          kind: "call",
          status: "running",
          name: "first",
        },
        {
          id: "tool-1",
          kind: "call",
          status: "running",
          name: "second",
        },
      ]),
      parsedMessage("message-2", [
        {
          id: "tool-1",
          kind: "result",
          status: "completed",
          name: "second",
          result: "done",
        },
      ]),
    ])

    expect(paired.resultsByCallKey.has(toolActivityKey(0, 0))).toBe(false)
    expect(paired.resultsByCallKey.get(toolActivityKey(0, 1))).toMatchObject({
      name: "second",
      result: "done",
    })
  })
})
