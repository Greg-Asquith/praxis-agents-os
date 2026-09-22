import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useReviewApprovalMutation } from "@/features/conversations/api/review-approval"
import { agentRunApprovalStateQueryOptions } from "@/features/conversations/api/get-approval-state"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import { setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"
import { jsonResponse, stubFetch } from "../../../support/fetch-stub"

const input = {
  runId: "root",
  approval_revision: "round-1",
  approval_id: "delegated-leaf",
  override_args: {
    source: { version: 1, entity_kind: "file", entity_id: "selected-file", label: "Selected file" },
  },
}
const active = {
  active_run: { id: "root", status: "awaiting_approval" },
  approval_revision: "round-2",
  latest_run: null,
  approval_expires_at: null,
}
const reviewed = {
  run_id: "root",
  approval_revision: "round-2",
  approvals: [
    {
      approval_id: "delegated-leaf",
      owner_run_id: "child",
      args: { _source: { revision_id: "server-pin" } },
    },
  ],
}
let client: QueryClient
function mutation() {
  let result: ReturnType<typeof useReviewApprovalMutation> | undefined
  function Probe() {
    result = useReviewApprovalMutation("conversation")
    return null
  }
  renderToStaticMarkup(createElement(QueryClientProvider, { client }, createElement(Probe)))
  if (!result) throw new Error("Review mutation was not rendered")
  return result
}
beforeEach(() => {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  setActiveUserId("operator")
  setActiveWorkspaceSlug("workspace")
})
afterEach(() => {
  client.clear()
  setActiveUserId(null)
  setActiveWorkspaceSlug(null)
  vi.unstubAllGlobals()
})
function recoveryResponse(path: string) {
  if (path.endsWith("active-run")) return jsonResponse(active)
  if (path.endsWith("approval-state")) return jsonResponse(reviewed)
  return jsonResponse({ messages: [], total: 0 })
}

describe("approval File re-review API recovery", () => {
  it("posts the leaf through the root and waits for retained approval and transcript recovery", async () => {
    let finishApproval: () => void = () => undefined
    const fetch = stubFetch((url, init) => {
      const path = url instanceof Request ? url.url : url.toString()
      if (init?.method === "POST") return jsonResponse(reviewed)
      if (path.endsWith("approval-state"))
        return new Promise<Response>((resolve) => {
          finishApproval = () => {
            resolve(jsonResponse(reviewed))
          }
        })
      return recoveryResponse(path)
    })
    let settled = false
    const request = mutation()
      .mutateAsync(input)
      .finally(() => {
        settled = true
      })
    await vi.waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(4)
    })
    expect(settled).toBe(false)
    const post = fetch.mock.calls.find(([, init]) => init?.method === "POST")
    const url = post?.[0]
    expect(url instanceof Request ? url.url : url?.toString()).toContain(
      "/agent-runs/root/review-approval"
    )
    const body = post?.[1]?.body
    if (typeof body !== "string") throw new Error("Expected a JSON review payload")
    expect(JSON.parse(body)).toEqual({
      approval_revision: "round-1",
      approval_id: "delegated-leaf",
      override_args: input.override_args,
    })
    expect(new Headers(post?.[1]?.headers).get("X-Workspace")).toBe("workspace")
    expect(post?.[1]?.credentials).toBe("include")
    finishApproval()
    await request
    expect(
      client.getQueryData(agentRunApprovalStateQueryOptions("root", "round-2").queryKey)
    ).toEqual(reviewed)
    expect(client.getQueryData(conversationsQueryKeys.activeRun("conversation"))).toEqual(active)
    expect(client.getQueryData(conversationsQueryKeys.messages("conversation"))).toEqual({
      messages: [],
      total: 0,
    })
    expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1)
  })

  it.each(["lost", "stale"])(
    "recovers before exposing a %s review response without replaying the POST",
    async (failure) => {
      let finishRead: () => void = () => undefined
      const fetch = stubFetch((url, init) => {
        const path = url instanceof Request ? url.url : url.toString()
        if (init?.method === "POST") {
          if (failure === "lost") throw new TypeError("Failed to fetch")
          return jsonResponse({ code: "approval_revision_conflict" }, { status: 409 })
        }
        if (path.endsWith("active-run"))
          return new Promise<Response>((resolve) => {
            finishRead = () => {
              resolve(jsonResponse(active))
            }
          })
        return recoveryResponse(path)
      })
      let settled = false
      const request = mutation()
        .mutateAsync(input)
        .catch((error: unknown) => error)
        .finally(() => {
          settled = true
        })
      await vi.waitFor(() => {
        expect(fetch).toHaveBeenCalledTimes(2)
      })
      expect(settled).toBe(false)
      finishRead()
      const error: unknown = await request
      expect(error).toBeInstanceOf(Error)
      expect(error instanceof Error ? error.message : null).toBe(
        failure === "lost"
          ? "Failed to fetch"
          : "These requests have changed. Refresh and review them again."
      )
      expect(
        client.getQueryData(agentRunApprovalStateQueryOptions("root", "round-2").queryKey)
      ).toEqual(reviewed)
      expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1)
    }
  )

  it("surfaces a recovery failure after a successful review without repeating the mutation", async () => {
    const fetch = stubFetch((url, init) => {
      const path = url instanceof Request ? url.url : url.toString()
      if (init?.method === "POST") return jsonResponse(reviewed)
      if (path.endsWith("active-run"))
        return jsonResponse({ detail: "Conversation unavailable" }, { status: 403 })
      return recoveryResponse(path)
    })
    await expect(mutation().mutateAsync(input)).rejects.toThrow("Conversation unavailable")
    expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1)
    expect(client.getQueryData(conversationsQueryKeys.activeRun("conversation"))).toBeUndefined()
  })
})
