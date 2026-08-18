import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import {
  collectStreamTouchedFiles,
  invalidateStreamQueries,
} from "@/features/conversations/stream/query-cache"
import type { StreamEvent } from "@/features/conversations/stream/protocol"
import { filesQueryKeys } from "@/features/files/api/list-files"

const envelope = { run_id: "run-1", conversation_id: "conversation-1", seq: 1 }

function runCodeResultEvent(fileId: string, updated: boolean): StreamEvent {
  return {
    event: "tool.result",
    data: {
      ...envelope,
      tool_call_id: "call-1",
      name: "run_code",
      result: {
        model: "gpt-5.6-luna",
        model_provider: "openai",
        outputs: [
          {
            kind: "file",
            media_type: "text/csv",
            name: "budget.csv",
            reference: { entity_id: fileId, entity_kind: "file", label: "budget.csv" },
            size_bytes: 12,
            revision_id: updated ? "revision-2" : null,
            revision_number: updated ? 2 : null,
            updated_existing: updated,
          },
        ],
        result: "Updated.",
        skipped_outputs: [],
      },
    },
  }
}

describe("stream query cache invalidation", () => {
  it("refreshes files touched by run_code once the stream finishes", async () => {
    const queryClient = new QueryClient()
    const touched = new Set<string>()
    const events: StreamEvent[] = [
      { event: "run.status", data: { ...envelope, status: "running" } },
      runCodeResultEvent("file-1", true),
      {
        event: "tool.result",
        data: { ...envelope, tool_call_id: "call-2", name: "read_file", result: {} },
      },
      { event: "done", data: { ...envelope, status: "completed" } },
    ]
    for (const event of events) {
      collectStreamTouchedFiles(touched, event)
    }
    for (const key of [
      filesQueryKeys.list({}),
      filesQueryKeys.folders(),
      filesQueryKeys.detail("file-1"),
      filesQueryKeys.revisions("file-1"),
      filesQueryKeys.preview("file-1"),
      filesQueryKeys.revisionContent("file-1", "revision-1"),
      filesQueryKeys.detail("file-2"),
      conversationsQueryKeys.messages("conversation-1"),
    ]) {
      queryClient.setQueryData(key, { stale: true })
    }

    expect([...touched]).toEqual(["file-1"])
    await invalidateStreamQueries(queryClient, {
      conversationCreated: false,
      conversationId: "conversation-1",
      status: "completed",
      touchedFileIds: touched,
    })

    const invalidated = (key: readonly unknown[]) =>
      queryClient.getQueryState(key)?.isInvalidated ?? false
    expect(invalidated(filesQueryKeys.list({}))).toBe(true)
    expect(invalidated(filesQueryKeys.folders())).toBe(true)
    expect(invalidated(filesQueryKeys.detail("file-1"))).toBe(true)
    expect(invalidated(filesQueryKeys.revisions("file-1"))).toBe(true)
    expect(invalidated(filesQueryKeys.preview("file-1"))).toBe(true)
    expect(invalidated(filesQueryKeys.revisionContent("file-1", "revision-1"))).toBe(true)
    expect(invalidated(filesQueryKeys.detail("file-2"))).toBe(false)
    expect(invalidated(conversationsQueryKeys.messages("conversation-1"))).toBe(true)
  })

  it("leaves file queries alone when run_code touched nothing", async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(filesQueryKeys.list({}), { stale: true })

    await invalidateStreamQueries(queryClient, {
      conversationCreated: false,
      conversationId: "conversation-1",
      status: "completed",
      touchedFileIds: new Set(),
    })

    expect(queryClient.getQueryState(filesQueryKeys.list({}))?.isInvalidated).toBe(false)
  })
})
