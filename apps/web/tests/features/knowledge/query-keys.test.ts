// apps/web/tests/features/knowledge/query-keys.test.ts

import { afterEach, describe, expect, it } from "vitest"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import { searchIntegrationSourcesQueryOptions } from "@/features/knowledge/api/search-integration-sources"
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
    expect(
      knowledgeQueryKeys.integrationSourceSearch({
        integrationResourceId: "resource-1",
        limit: 20,
        query: "handbook",
      })
    ).toEqual([
      "knowledge",
      "user-1",
      "acme",
      "integration-source-search",
      { integrationResourceId: "resource-1", limit: 20, query: "handbook" },
    ])
  })

  it("keeps integration searches disabled until submission and normalizes their keys", () => {
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")

    expect(searchIntegrationSourcesQueryOptions(null).enabled).toBe(false)
    expect(
      searchIntegrationSourcesQueryOptions({
        integrationResourceId: "resource-1",
        query: "  handbook  ",
      }).queryKey
    ).toEqual([
      "knowledge",
      "user-1",
      "acme",
      "integration-source-search",
      { integrationResourceId: "resource-1", limit: 20, query: "handbook" },
    ])
  })
})
