// apps/web/tests/features/knowledge/query-keys.test.ts

import { afterEach, describe, expect, it } from "vitest"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import { clearActiveWorkspace, setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
  clearActiveWorkspace()
})

describe("knowledge query keys", () => {
  it("scopes lists, details, and searches to the active user and workspace", () => {
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")

    expect(knowledgeQueryKeys.list({ limit: 100 })).toEqual([
      "knowledge",
      "user-1",
      "acme",
      "list",
      { limit: 100 },
    ])
    expect(knowledgeQueryKeys.detail("document-1")).toEqual([
      "knowledge",
      "user-1",
      "acme",
      "detail",
      "document-1",
    ])
    expect(knowledgeQueryKeys.search("vpn")).toEqual([
      "knowledge",
      "user-1",
      "acme",
      "search",
      "vpn",
    ])
  })
})
