import { QueryClient } from "@tanstack/react-query"
import { expect, it } from "vitest"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import {
  collectStreamSavedFiles,
  invalidateStreamQueries,
  seedStreamQueryCache,
  type StreamSavedFiles,
} from "@/features/conversations/stream/query-cache"
import type { ConversationActiveRunResponse } from "@/features/conversations/types"
import { filesQueryKeys } from "@/features/files/api/list-files"
import { approvalIdentity } from "../../../support/approvals"

const envelope = { run_id: "run-1", conversation_id: "conversation-1", seq: 1 }

it("preserves the same-run proposal revision through awaiting status and clears it on execution", () => {
  const client = new QueryClient()
  const key = conversationsQueryKeys.activeRun("conversation-1")
  client.setQueryData(key, { active_run: { id: "run-1", status: "running" }, latest_run: null })
  seedStreamQueryCache(client, {
    event: "tool.approval_required",
    data: {
      ...envelope,
      ...approvalIdentity("call"),
      tool_call_id: "call",
      name: "write_file",
      args: {},
      approval_revision: "new-round",
    },
  })
  seedStreamQueryCache(client, {
    event: "run.status",
    data: { ...envelope, status: "awaiting_approval" },
  })
  expect(client.getQueryData<ConversationActiveRunResponse>(key)?.approval_revision).toBe(
    "new-round"
  )
  seedStreamQueryCache(client, { event: "run.status", data: { ...envelope, status: "running" } })
  expect(client.getQueryData<ConversationActiveRunResponse>(key)?.approval_revision).toBeNull()
})

it("refreshes Files saved by a nested document edit once the stream ends", async () => {
  const client = new QueryClient()
  const saved: StreamSavedFiles = { callNames: new Map(), fileIds: new Set() }
  const nested = { ...envelope, tool_call_id: "child-1", parent_tool_call_id: "script-1" }
  collectStreamSavedFiles(saved, {
    event: "tool.call",
    data: { ...nested, name: "edit_workbook", args: null },
  })
  // Nested results can arrive without a name.
  collectStreamSavedFiles(saved, {
    event: "tool.result",
    data: {
      ...nested,
      name: null,
      result: {
        file_id: "file-1",
        name: "Budget.xlsx",
        revision_id: "revision-2",
        revision_number: 2,
        changes: [],
      },
    },
  })
  for (const key of [
    filesQueryKeys.list({}),
    filesQueryKeys.revisions("file-1"),
    filesQueryKeys.detail("file-2"),
  ]) {
    client.setQueryData(key, { stale: true })
  }

  await invalidateStreamQueries(client, {
    conversationCreated: false,
    conversationId: "conversation-1",
    savedFileIds: saved.fileIds,
    status: "completed",
  })

  const invalidated = (key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated
  expect(invalidated(filesQueryKeys.list({}))).toBe(true)
  expect(invalidated(filesQueryKeys.revisions("file-1"))).toBe(true)
  expect(invalidated(filesQueryKeys.detail("file-2"))).toBe(false)
})
