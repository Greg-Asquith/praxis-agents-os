import { QueryClient } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { auditEventsQueryOptions } from "@/features/audit/api/list-audit-events"
import { setActiveWorkspaceSlug } from "@/lib/workspace"
import { getFetchRequest, jsonResponse, stubFetch } from "../../../support/fetch-stub"

beforeEach(() => {
  setActiveWorkspaceSlug("acme")
})

afterEach(() => {
  setActiveWorkspaceSlug(null)
  vi.unstubAllGlobals()
})

describe("audit event list API", () => {
  it("serializes tool filters with the exact backend query keys", async () => {
    const fetchStub = stubFetch(jsonResponse({ events: [], limit: 50, offset: 0, total: 0 }))
    const queryClient = new QueryClient()

    await queryClient.fetchQuery(
      auditEventsQueryOptions({
        toolName: "gmail_search_messages",
        toolProvider: "gmail",
      })
    )

    const { init, url } = getFetchRequest(fetchStub)
    expect(url.href).toBe(
      "http://localhost:8000/api/v1/audit-events/?limit=50&offset=0&tool_name=gmail_search_messages&tool_provider=gmail"
    )
    expect(init).toMatchObject({ credentials: "include", method: "GET" })
    expect(new Headers(init.headers).get("X-Workspace")).toBe("acme")
  })

  it("leaves absent tool filters undefined", async () => {
    const fetchStub = stubFetch(jsonResponse({ events: [], limit: 50, offset: 0, total: 0 }))
    const queryClient = new QueryClient()

    await queryClient.fetchQuery(auditEventsQueryOptions())

    const { url } = getFetchRequest(fetchStub)
    expect(url.href).toBe("http://localhost:8000/api/v1/audit-events/?limit=50&offset=0")
  })
})
