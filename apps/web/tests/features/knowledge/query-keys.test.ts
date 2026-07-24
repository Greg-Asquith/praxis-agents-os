// apps/web/tests/features/knowledge/query-keys.test.ts

import { afterEach, describe, expect, it } from "vitest"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import { setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
  setActiveWorkspaceSlug(null)
})

describe("knowledge query keys", () => {
  it("scopes lists, details, and searches to the active workspace", () => {
    setActiveWorkspaceSlug("acme")

    expect(knowledgeQueryKeys.list({ limit: 100 })).toEqual([
      "knowledge",
      "acme",
      "list",
      { limit: 100 },
    ])
    expect(knowledgeQueryKeys.detail("document-1")).toEqual([
      "knowledge",
      "acme",
      "detail",
      "document-1",
    ])
    expect(knowledgeQueryKeys.search("vpn")).toEqual(["knowledge", "acme", "search", "vpn"])
  })
})
