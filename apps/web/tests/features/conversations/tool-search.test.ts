// apps/web/tests/features/conversations/tool-search.test.ts

import { describe, expect, it } from "vitest"

import {
  toolSearchQuery,
  toolSearchResult,
} from "@/features/conversations/native-tools/tool-search"

describe("tool search parsing", () => {
  it("reads native and local search shapes", () => {
    expect(toolSearchQuery('{"queries": ["google ads", " ", "budget"]}')).toBe("google ads, budget")
    expect(
      toolSearchResult({
        discovered_tools: [{ name: "list_campaigns" }, { name: "list_campaigns" }],
      })
    ).toEqual({ toolNames: ["list_campaigns"] })
    expect(
      toolSearchResult({ return_value: { discovered_tools: [], message: "No matches" } })
    ).toEqual({ toolNames: [] })
    expect(toolSearchResult("No tools matched")).toBeNull()
  })
})
