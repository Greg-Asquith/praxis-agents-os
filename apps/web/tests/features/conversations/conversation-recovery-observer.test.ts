import {
  environmentManager,
  focusManager,
  onlineManager,
  QueryObserver,
} from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { createQueryClient } from "@/app/query-client"
import { conversationActiveRunQueryOptions } from "@/features/conversations/api/get-active-run"
import {
  conversationActiveRunRefetchInterval,
  createConversationRecoveryCounter,
  isConversationReadRecoverable,
} from "@/features/conversations/conversation-heal-polling"
import type { AgentRun, ConversationActiveRunResponse } from "@/features/conversations/types"
import { ApiError } from "@/lib/api/errors"
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
    onlineManager.setOnline(true)
    focusManager.setFocused(true)
  })

  afterEach(() => {
    unsubscribe?.()
    unsubscribe = undefined
    client.unmount()
    client.clear()
    environmentManager.setIsServer(() => wasServer)
    setActiveUserId(null)
    setActiveWorkspaceSlug(null)
    onlineManager.setOnline(true)
    focusManager.setFocused(true)
    vi.resetAllMocks()
    vi.useRealTimers()
  })

  function observe(streamConnected = false) {
    const count = createConversationRecoveryCounter()
    const observer = new QueryObserver(client, {
      ...conversationActiveRunQueryOptions("conversation-1"),
      refetchOnWindowFocus: (query) =>
        query.state.error === null || isConversationReadRecoverable(query.state.error),
      refetchOnReconnect: (query) =>
        query.state.error === null || isConversationReadRecoverable(query.state.error),
      refetchInterval: (query) =>
        conversationActiveRunRefetchInterval(
          query.state.data,
          query.state.error,
          streamConnected,
          Date.now(),
          count(query.state)
        ),
    })
    unsubscribe = observer.subscribe(vi.fn())
    return observer
  }

  it.each(["awaiting_approval", "completed", "failed", "cancelled"] as const)(
    "recovers %s through timed reads while the stream is disconnected",
    async (status) => {
      vi.mocked(apiRequest)
        .mockResolvedValueOnce(response("running"))
        .mockRejectedValueOnce(new TypeError("Failed to fetch"))
        .mockRejectedValueOnce(new TypeError("Failed to fetch"))
        .mockRejectedValueOnce(new TypeError("Failed to fetch"))
        .mockResolvedValueOnce(response(status))
      const observer = observe()
      await vi.advanceTimersByTimeAsync(0)
      expect(observer.getCurrentResult().data?.active_run?.status).toBe("running")

      await vi.advanceTimersByTimeAsync(3_999)
      expect(apiRequest).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(3_001)
      expect(observer.getCurrentResult().isError).toBe(true)
      expect(observer.getCurrentResult().data?.active_run?.status).toBe("running")
      await vi.advanceTimersByTimeAsync(4_000)
      expect(observer.getCurrentResult().data).toEqual(response(status))
      expect(
        client.getQueryData(conversationActiveRunQueryOptions("conversation-1").queryKey)
      ).toEqual(response(status))
      expect(vi.mocked(apiRequest).mock.calls[1]?.[0]).toBe(
        "/conversations/conversation-1/active-run"
      )
      expect(vi.mocked(apiRequest).mock.calls[1]?.[1]?.signal).toBeInstanceOf(AbortSignal)
      await vi.advanceTimersByTimeAsync(60_000)
      expect(apiRequest).toHaveBeenCalledTimes(5)
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
  it.each([503, 429, "network"] as const)(
    "recovers after exhausted %s retries with capped delays and resets after success",
    async (kind) => {
      const error =
        kind === "network"
          ? new TypeError("Failed to fetch")
          : new ApiError({ status: kind, message: "Unavailable", problem: null })
      vi.mocked(apiRequest).mockRejectedValue(error)
      const observer = observe()
      await vi.advanceTimersByTimeAsync(3_000)
      expect(apiRequest).toHaveBeenCalledTimes(3)
      expect(observer.getCurrentResult().isError).toBe(true)
      for (const [index, delay] of [4_000, 8_000, 16_000, 30_000, 30_000].entries()) {
        const before = 3 * (index + 1)
        await vi.advanceTimersByTimeAsync(delay - 1)
        expect(apiRequest).toHaveBeenCalledTimes(before)
        await vi.advanceTimersByTimeAsync(3_001)
        expect(apiRequest).toHaveBeenCalledTimes(before + 3)
      }
      vi.mocked(apiRequest).mockResolvedValue(response("running"))
      await vi.advanceTimersByTimeAsync(30_000)
      expect(observer.getCurrentResult().isError).toBe(false)
      const count = vi.mocked(apiRequest).mock.calls.length
      await vi.advanceTimersByTimeAsync(3_999)
      expect(apiRequest).toHaveBeenCalledTimes(count)
      await vi.advanceTimersByTimeAsync(1)
      expect(apiRequest).toHaveBeenCalledTimes(count + 1)
      vi.mocked(apiRequest).mockRejectedValue(error)
      await vi.advanceTimersByTimeAsync(7_000)
      const failedCount = vi.mocked(apiRequest).mock.calls.length
      await vi.advanceTimersByTimeAsync(4_000)
      expect(apiRequest).toHaveBeenCalledTimes(failedCount + 1)
    }
  )

  it.each([401, 403, 404, "abort"] as const)("stops automatic reads for %s", async (kind) => {
    const error =
      kind === "abort"
        ? new DOMException("Cancelled", "AbortError")
        : new ApiError({ status: kind, message: "Unavailable", problem: null })
    vi.mocked(apiRequest).mockRejectedValue(error)
    const observer = observe()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(apiRequest).toHaveBeenCalledTimes(1)
    expect(observer.getCurrentResult().error).toBe(error)
    focusManager.setFocused(false)
    focusManager.setFocused(true)
    onlineManager.setOnline(false)
    onlineManager.setOnline(true)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it.each([true, false])(
    "refreshes parked approvals after focus and reconnect with expiry enabled=%s",
    async (expiry) => {
      const parked = {
        ...response("awaiting_approval"),
        approval_revision: "first",
        approval_expires_at: expiry ? "2026-09-15T12:00:00Z" : null,
      }
      vi.mocked(apiRequest).mockResolvedValue(parked)
      const observer = observe()
      await vi.advanceTimersByTimeAsync(60_000)
      expect(apiRequest).toHaveBeenCalledTimes(1)
      focusManager.setFocused(false)
      vi.mocked(apiRequest).mockResolvedValue({ ...parked, approval_revision: "second" })
      focusManager.setFocused(true)
      await vi.advanceTimersByTimeAsync(0)
      expect(observer.getCurrentResult().data?.approval_revision).toBe("second")
      onlineManager.setOnline(false)
      await vi.advanceTimersByTimeAsync(60_000)
      vi.mocked(apiRequest).mockResolvedValue(response("completed"))
      onlineManager.setOnline(true)
      await vi.advanceTimersByTimeAsync(0)
      expect(observer.getCurrentResult().data?.latest_run?.status).toBe("completed")
      expect(apiRequest).toHaveBeenCalledTimes(3)
    }
  )

  it("recovers a failure at the approval deadline while retaining the parked run", async () => {
    const parked = { ...response("awaiting_approval"), approval_expires_at: "2026-09-08T12:00:10Z" }
    vi.mocked(apiRequest)
      .mockResolvedValueOnce(parked)
      .mockRejectedValue(new TypeError("Failed to fetch"))
    const observer = observe()
    await vi.advanceTimersByTimeAsync(18_000)
    expect(observer.getCurrentResult().data).toEqual(parked)
    expect(observer.getCurrentResult().isError).toBe(true)
    vi.mocked(apiRequest).mockResolvedValue(response("failed"))
    await vi.advanceTimersByTimeAsync(4_000)
    expect(observer.getCurrentResult().data?.latest_run?.status).toBe("failed")
    expect(observer.getCurrentResult().isError).toBe(false)
  })
  it("waits while offline and resumes an initial read on reconnect", async () => {
    onlineManager.setOnline(false)
    vi.mocked(apiRequest).mockResolvedValue(response("completed"))
    const observer = observe()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(observer.getCurrentResult().isPaused).toBe(true)
    expect(apiRequest).not.toHaveBeenCalled()
    onlineManager.setOnline(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(observer.getCurrentResult().data).toEqual(response("completed"))
    expect(apiRequest).toHaveBeenCalledOnce()
  })
})
