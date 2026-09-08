import { environmentManager, QueryObserver } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { shouldRenderConversationStream } from "@/features/conversations/hooks/use-conversation-run-state"
import { resolveConversationActiveRun } from "@/features/conversations/run-state"
import { createQueryClient } from "@/app/query-client"
import { conversationRecoveryQueryOptions } from "@/features/conversations/api/get-conversation-recovery"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import {
  conversationActiveRunRefetchInterval,
  createConversationRecoveryCounter,
} from "@/features/conversations/conversation-heal-polling"
import type { AgentRun, ConversationActiveRunResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"
import { setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

vi.mock("@/lib/api/client", () => ({ apiRequest: vi.fn(), setApiRequestHeadersProvider: vi.fn() }))

const run: AgentRun = {
  id: "root",
  conversation_id: "conversation",
  agent_id: "agent",
  workspace_id: "workspace",
  user_id: "user",
  parent_run_id: null,
  delegation_depth: 0,
  trigger: "interactive",
  status: "awaiting_approval",
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
const messages = { messages: [{ id: "retained-transcript" }], total: 1 }
function projection(revision = "first"): ConversationActiveRunResponse {
  return {
    active_run: run,
    latest_run: run,
    approval_expires_at: null,
    approval_revision: revision,
  }
}
const approval = (revision: string) => ({
  run_id: run.id,
  approval_revision: revision,
  approvals: [{ approval_id: revision, tool_call_id: "same-native-id", args: { text: revision } }],
  delegations: [],
})

describe("coordinated conversation recovery reads", () => {
  let client: ReturnType<typeof createQueryClient>
  let stop: (() => void) | undefined
  let wasServer: boolean
  beforeEach(() => {
    vi.useFakeTimers()
    wasServer = environmentManager.isServer()
    environmentManager.setIsServer(() => false)
    setActiveUserId("user")
    setActiveWorkspaceSlug("workspace")
    client = createQueryClient()
    client.mount()
  })
  afterEach(() => {
    stop?.()
    stop = undefined
    client.unmount()
    client.clear()
    environmentManager.setIsServer(() => wasServer)
    setActiveUserId(null)
    setActiveWorkspaceSlug(null)
    vi.resetAllMocks()
    vi.useRealTimers()
  })

  it("deduplicates Retry, reads the active run first, and refreshes a new revision on the same run", async () => {
    const options = conversationRecoveryQueryOptions(client, "conversation")
    client.setQueryData(options.queryKey, projection())
    client.setQueryData(conversationsQueryKeys.messages("conversation"), messages)
    client.setQueryData(
      [...conversationsQueryKeys.approvalState("root"), "first"],
      approval("first")
    )
    let release: ((value: ConversationActiveRunResponse) => void) | undefined
    vi.mocked(apiRequest).mockImplementation((path) => {
      if (path.endsWith("active-run"))
        return new Promise((resolve) => {
          release = resolve
        })
      return Promise.resolve(path.endsWith("messages") ? messages : approval("second"))
    })
    const first = client.fetchQuery({ ...options, staleTime: 0 })
    const second = client.fetchQuery({ ...options, staleTime: 0 })
    expect(apiRequest).toHaveBeenCalledTimes(1)
    expect(client.getQueryData(conversationsQueryKeys.messages("conversation"))).toEqual(messages)
    release?.(projection("second"))
    await Promise.all([first, second])
    expect(vi.mocked(apiRequest).mock.calls.map(([path]) => path)).toEqual([
      "/conversations/conversation/active-run",
      "/conversations/conversation/messages",
      "/agent-runs/root/approval-state",
    ])
    expect(
      client.getQueryData([...conversationsQueryKeys.approvalState("root"), "second"])
    ).toEqual(approval("second"))
    expect(client.getQueryData(options.queryKey)).toEqual(projection("second"))
  })

  it.each(["messages", "approval-state"])(
    "recovers %s failures without publishing an incomplete proposal",
    async (failedRead) => {
      const options = conversationRecoveryQueryOptions(client, "conversation")
      const count = createConversationRecoveryCounter()
      client.setQueryData(options.queryKey, projection())
      client.setQueryData(conversationsQueryKeys.messages("conversation"), messages)
      let failing = true
      vi.mocked(apiRequest).mockImplementation((path) => {
        if (failing && path.endsWith(failedRead))
          return Promise.reject(new TypeError("Failed to fetch"))
        return Promise.resolve(
          path.endsWith("active-run")
            ? projection("second")
            : path.endsWith("messages")
              ? messages
              : approval("second")
        )
      })
      const observer = new QueryObserver(client, {
        ...options,
        staleTime: 0,
        refetchInterval: (query) =>
          conversationActiveRunRefetchInterval(
            query.state.data,
            query.state.error,
            false,
            Date.now(),
            count(query.state)
          ),
      })
      stop = observer.subscribe(vi.fn())
      await vi.advanceTimersByTimeAsync(3_000)
      expect(observer.getCurrentResult().isError).toBe(true)
      expect(observer.getCurrentResult().data?.approval_revision).toBe("first")
      expect(client.getQueryData(conversationsQueryKeys.messages("conversation"))).toEqual(messages)
      failing = false
      await vi.advanceTimersByTimeAsync(4_000)
      expect(observer.getCurrentResult().data?.approval_revision).toBe("second")
      expect(observer.getCurrentResult().isError).toBe(false)
      expect(
        vi
          .mocked(apiRequest)
          .mock.calls.every(([, options]) => !options?.method || options.method === "GET")
      ).toBe(true)
    }
  )

  it.each(["running", "completed", "failed", "cancelled"] as const)(
    "does not reload old approvals when the durable run is %s",
    async (status) => {
      const current = { ...run, status }
      const response = {
        ...projection(),
        active_run: status === "running" ? current : null,
        latest_run: current,
      }
      vi.mocked(apiRequest).mockImplementation((path) =>
        Promise.resolve(path.endsWith("active-run") ? response : messages)
      )
      await client.fetchQuery(conversationRecoveryQueryOptions(client, "conversation"))
      expect(apiRequest).toHaveBeenCalledTimes(2)
      expect(client.getQueryData(conversationsQueryKeys.activeRun("conversation"))).toEqual(
        response
      )
    }
  )

  it("stops dependent reads after a workspace switch and leaves the other cache untouched", async () => {
    const options = conversationRecoveryQueryOptions(client, "conversation")
    let release: ((value: ConversationActiveRunResponse) => void) | undefined
    vi.mocked(apiRequest).mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve
        })
    )
    const read = client.fetchQuery(options).catch((error: unknown) => error)
    setActiveWorkspaceSlug("other-workspace")
    const otherKey = conversationsQueryKeys.activeRun("conversation")
    client.setQueryData(otherKey, projection("other"))
    release?.(projection("second"))
    await read
    expect(apiRequest).toHaveBeenCalledTimes(1)
    expect(client.getQueryData(otherKey)).toEqual(projection("other"))
  })
  it("keeps a connected stream authoritative and discards its disconnected running state", () => {
    const streamed = { ...run, status: "running" as const }
    expect(resolveConversationActiveRun(run, streamed, true)).toBe(streamed)
    expect(resolveConversationActiveRun(run, streamed, false)).toBe(run)
    expect(resolveConversationActiveRun(null, streamed, false)).toBeNull()
  })
  it("aborts dependent reads when the recovery observer unmounts", async () => {
    let messageSignal: AbortSignal | null | undefined
    vi.mocked(apiRequest).mockImplementation((path, options) => {
      if (path.endsWith("active-run")) return Promise.resolve({ ...projection(), active_run: null })
      messageSignal = options?.signal
      return new Promise((_resolve, reject) => {
        messageSignal?.addEventListener(
          "abort",
          () => {
            reject(new DOMException("Cancelled", "AbortError"))
          },
          { once: true }
        )
      })
    })
    const observer = new QueryObserver(
      client,
      conversationRecoveryQueryOptions(client, "conversation")
    )
    stop = observer.subscribe(vi.fn())
    await vi.advanceTimersByTimeAsync(0)
    expect(messageSignal?.aborted).toBe(false)
    stop()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(messageSignal?.aborted).toBe(true)
    expect(apiRequest).toHaveBeenCalledTimes(2)
  })
  it("removes disconnected live activity when a durable terminal outcome has no assistant message", () => {
    expect(
      shouldRenderConversationStream({
        activeRun: null,
        conversationId: "conversation",
        hasPersistedStreamResponse: false,
        streamConversationId: "conversation",
        submittingApprovalRunId: null,
        durableRunSettled: true,
      })
    ).toBe(false)
  })
  it("retries a revision change between status and approval reads before publishing", async () => {
    let statusReads = 0
    vi.mocked(apiRequest).mockImplementation((path) => {
      if (path.endsWith("active-run")) {
        statusReads += 1
        return Promise.resolve(projection(statusReads === 1 ? "first" : "second"))
      }
      return Promise.resolve(path.endsWith("messages") ? messages : approval("second"))
    })
    const observer = new QueryObserver(
      client,
      conversationRecoveryQueryOptions(client, "conversation")
    )
    stop = observer.subscribe(vi.fn())
    await vi.advanceTimersByTimeAsync(0)
    expect(observer.getCurrentResult().data).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1_000)
    expect(observer.getCurrentResult().data?.approval_revision).toBe("second")
    expect(statusReads).toBe(2)
  })
})
