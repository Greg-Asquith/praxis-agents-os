import { QueryClient } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { auditEventsQueryOptions } from "@/features/audit/api/list-audit-events"

const { apiRequest } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}))

vi.mock("@/lib/api/client", () => ({
  apiRequest,
  setApiRequestHeadersProvider: vi.fn(),
}))

beforeEach(() => {
  apiRequest.mockReset()
  apiRequest.mockResolvedValue({ events: [], limit: 50, offset: 0, total: 0 })
})

describe("audit event list API", () => {
  it("serializes tool filters with the exact backend query keys", async () => {
    const queryClient = new QueryClient()

    await queryClient.fetchQuery(
      auditEventsQueryOptions({
        toolName: "gmail_search_messages",
        toolProvider: "gmail",
      })
    )

    expect(apiRequest).toHaveBeenCalledWith("/audit-events/", {
      query: {
        action: undefined,
        actor_user_id: undefined,
        limit: 50,
        offset: 0,
        occurred_after: undefined,
        occurred_before: undefined,
        resource_id: undefined,
        resource_type: undefined,
        status: undefined,
        tool_name: "gmail_search_messages",
        tool_provider: "gmail",
      },
    })
  })

  it("leaves absent tool filters undefined", async () => {
    const queryClient = new QueryClient()

    await queryClient.fetchQuery(auditEventsQueryOptions())

    expect(apiRequest).toHaveBeenCalledWith("/audit-events/", {
      query: {
        action: undefined,
        actor_user_id: undefined,
        limit: 50,
        offset: 0,
        occurred_after: undefined,
        occurred_before: undefined,
        resource_id: undefined,
        resource_type: undefined,
        status: undefined,
        tool_name: undefined,
        tool_provider: undefined,
      },
    })
  })
})
