import { createElement, Suspense } from "react"
import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { HomeStats } from "@/features/home/components/home-stats"
import {
  statusQueryKeys,
  statusSummaryQueryOptions,
} from "@/features/status/api/get-status-summary"
import type { StatusSummary } from "@/features/status/types"
import { renderHomeComponent } from "./test-utils"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("HomeStats", () => {
  it("renders the exact backend summary without list-derived filtering", () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData<StatusSummary>(statusQueryKeys.summary(), {
      unread_conversations: 143,
      conversations_needing_approval: 121,
      schedules_needing_attention: 109,
    })

    const html = renderHomeComponent(createElement(HomeStats), queryClient)

    expect(html).toContain("Agents Waiting for Approval")
    expect(html).toContain(">121<")
    expect(html).toContain("Unread Conversations")
    expect(html).toContain(">143<")
    expect(html).toContain("Schedules Requiring Attention")
    expect(html).toContain(">109<")
  })

  it("shows a loading state instead of temporary zero counts", () => {
    const html = renderHomeComponent(
      createElement(
        Suspense,
        { fallback: createElement("p", null, "Loading home statistics") },
        createElement(HomeStats)
      )
    )

    expect(html).toContain("Loading home statistics")
    expect(html).not.toContain("Unread Conversations")
  })

  it("keeps failed summary requests out of the cache instead of fabricating zeros", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Unavailable" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        })
      )
    )
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    await expect(queryClient.fetchQuery(statusSummaryQueryOptions())).rejects.toBeDefined()
    expect(queryClient.getQueryData(statusQueryKeys.summary())).toBeUndefined()
  })
})
