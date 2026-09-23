import type * as ApiClient from "@/lib/api/client"
import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { parseResultPreview } from "@/components/tool-ui/result-preview"
import { retainedResultQueryOptions } from "@/components/tool-ui/result-preview-query"
import { apiRequest } from "@/lib/api/client"
import { setActiveWorkspaceSlug } from "@/lib/workspace"
import { cases, envelope } from "../../integrations/result-preview-fixtures"

vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof ApiClient>()),
  apiRequest: vi.fn(),
}))

afterEach(() => {
  vi.resetAllMocks()
  setActiveWorkspaceSlug(null)
})

function options() {
  const preview = parseResultPreview(envelope("google_ads", cases[0]?.data))
  if (!preview) throw new Error("Invalid test preview")
  return retainedResultQueryOptions(preview)
}

describe("retained result reads", () => {
  it("loads the initial revision through the authenticated API and retains every row", async () => {
    const data = {
      results: [{ data: { rows: Array.from({ length: 1000 }, (_, id) => ({ id })) } }],
    }
    vi.mocked(apiRequest)
      .mockResolvedValueOnce({
        revisions: [
          { id: "edited", revision_number: 2 },
          { id: "original", revision_number: 1 },
        ],
      })
      .mockResolvedValueOnce({ content: JSON.stringify(data) })
    const query = options()
    const value = await new QueryClient().fetchQuery(query)
    expect(value).toEqual(data)
    expect(apiRequest).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/revisions/original/content"),
      expect.objectContaining({ signal: expect.any(AbortSignal) as AbortSignal })
    )
  })

  it.each(["not JSON", JSON.stringify({ results: [{ data: { rows: [] } }] })])(
    "rejects incomplete or invalid saved data",
    async (content) => {
      vi.mocked(apiRequest)
        .mockResolvedValueOnce({ revisions: [{ id: "original", revision_number: 1 }] })
        .mockResolvedValueOnce({ content })
      await expect(new QueryClient().fetchQuery(options())).rejects.toThrow()
    }
  )

  it("does not substitute an edited revision when the original is unavailable", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      revisions: [{ id: "edited", revision_number: 2 }],
    })
    await expect(new QueryClient().fetchQuery(options())).rejects.toThrow("unavailable")
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it("isolates loaded results across workspace caches", () => {
    setActiveWorkspaceSlug("first")
    const first = options().queryKey
    setActiveWorkspaceSlug("second")
    expect(options().queryKey).not.toEqual(first)
  })
})
