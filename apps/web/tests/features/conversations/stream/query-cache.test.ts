import { QueryClient } from "@tanstack/react-query"
import { expect, it } from "vitest"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import { seedStreamQueryCache } from "@/features/conversations/stream/query-cache"
import type { ConversationActiveRunResponse } from "@/features/conversations/types"
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
