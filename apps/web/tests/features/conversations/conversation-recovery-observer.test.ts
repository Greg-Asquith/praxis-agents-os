import { environmentManager, QueryObserver } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { createQueryClient } from "@/app/query-client"
import { conversationActiveRunQueryOptions } from "@/features/conversations/api/get-active-run"
import { conversationActiveRunRefetchInterval } from "@/features/conversations/conversation-heal-polling"
import type { AgentRun, ConversationActiveRunResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"
import type * as ApiClient from "@/lib/api/client"
import { setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  apiRequest: vi.fn(),
}))

const run: AgentRun = {
  id: "run-1",
  conversation_id: "conversation-1",
  agent_id: "agent-1",
  workspace_id: "workspace-1",
  user_id: "user-1",
  parent_run_id: null,
  delegation_depth: 0,
  trigger: "interactive",
  status: "running",
  model_name: null,
  started_at: null,
  completed_at: null,
  failed_at: null,
  lease_expires_at: null,
  error_code: null,
  error_message: null,
  outcome: null,
  completion_json: null,
  created_at: "2026-09-08T12:00:00Z",
  updated_at: "2026-09-08T12:00:00Z",
}

function response(status: AgentRun["status"]): ConversationActiveRunResponse {
  const latest = { ...run, status }
  return {
    active_run: ["pending", "running", "awaiting_approval"].includes(status) ? latest : null,
    latest_run: latest,
    approval_expires_at: null,
  }
}

describe("conversation recovery through a query observer", () => {
  let client: ReturnType<typeof createQueryClient>
  let unsubscribe: (() => void) | undefined
  let wasServer: boolean

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-09-08T12:00:00Z"))
    wasServer = environmentManager.isServer()
    // Query-core disables interval timers on the server; no DOM is needed.
    environmentManager.setIsServer(() => false)
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("workspace-1")
    client = createQueryClient()
    client.mount()
  })

  afterEach(() => {
    unsubscribe?.()
    unsubscribe = undefined
    client.unmount()
    client.clear()
    environmentManager.setIsServer(() => wasServer)
    setActiveUserId(null)
    setActiveWorkspaceSlug(null)
    vi.resetAllMocks()
    vi.useRealTimers()
  })

  function observe(streamConnected = false) {
    const observer = new QueryObserver(client, {
      ...conversationActiveRunQueryOptions("conversation-1"),
      refetchInterval: (query) =>
        conversationActiveRunRefetchInterval(query.state.data, query.state.error, streamConnected),
    })
    unsubscribe = observer.subscribe(vi.fn())
    return observer
  }

  it.each(["awaiting_approval", "completed", "failed", "cancelled"] as const)(
    "recovers %s through timed reads while the stream is disconnected",
    async (status) => {
      vi.mocked(apiRequest)
        .mockResolvedValueOnce(response("running"))
        .mockResolvedValueOnce(response(status))
      const observer = observe()
      await vi.advanceTimersByTimeAsync(0)
      expect(observer.getCurrentResult().data?.active_run?.status).toBe("running")

      await vi.advanceTimersByTimeAsync(3_999)
      expect(apiRequest).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(1)
      expect(observer.getCurrentResult().data).toEqual(response(status))
      expect(
        client.getQueryData(conversationActiveRunQueryOptions("conversation-1").queryKey)
      ).toEqual(response(status))
      expect(apiRequest).toHaveBeenNthCalledWith(2, "/conversations/conversation-1/active-run")
      await vi.advanceTimersByTimeAsync(60_000)
      expect(apiRequest).toHaveBeenCalledTimes(2)
    }
  )

  it("does not poll while this conversation has a connected stream", async () => {
    vi.mocked(apiRequest).mockResolvedValue(response("running"))
    const observer = observe(true)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(observer.getCurrentResult().data?.active_run?.status).toBe("running")
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it("stops interval reads when the last observer unsubscribes", async () => {
    vi.mocked(apiRequest).mockResolvedValue(response("running"))
    observe()
    await vi.advanceTimersByTimeAsync(4_000)
    expect(apiRequest).toHaveBeenCalledTimes(2)
    unsubscribe?.()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(apiRequest).toHaveBeenCalledTimes(2)
    client.clear()
    expect(vi.getTimerCount()).toBe(0)
  })
})
