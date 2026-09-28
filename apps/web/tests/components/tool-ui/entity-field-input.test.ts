import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  entityReferenceHydrationQueryOptions,
  entityReferenceSearchQueryOptions,
  mergeEntityChoices,
} from "@/components/tool-ui/entity-reference-queries"
import type { EntityChoice } from "@/features/tools/types"
import { setActiveWorkspaceSlug } from "@/lib/workspace"
import {
  getFetchRequest,
  getJsonRequestBody,
  jsonResponse,
  stubFetch,
} from "../../support/fetch-stub"

describe("EntityFieldInput", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("projects declared dependencies before caching and sending lookups", async () => {
    const fetchStub = stubFetch(jsonResponse({ entity_kind: "file", choices: [] }))
    const client = new QueryClient()
    const base = {
      conversationId: "conversation-1",
      toolName: "read_file",
      fieldKey: "file_id",
      exactValues: [{ entity_id: "selected-file" }],
      dependentArgs: { account: "first", content: "PRIVATE_CONTENT", name: "draft" },
      dependsOn: ["account"],
    }
    setActiveWorkspaceSlug("first-workspace")
    const first = entityReferenceHydrationQueryOptions(base)
    const edited = entityReferenceHydrationQueryOptions({
      ...base,
      dependentArgs: { ...base.dependentArgs, content: "EDITED_CONTENT", name: "edited" },
    })
    expect(edited.queryKey).toEqual(first.queryKey)
    expect(JSON.stringify(first.queryKey)).not.toMatch(/PRIVATE_CONTENT|content|draft/)
    await client.fetchQuery(first)
    expect(getJsonRequestBody(getFetchRequest(fetchStub).init)).toMatchObject({
      dependent_args: { account: "first" },
    })
    expect(
      entityReferenceHydrationQueryOptions({
        ...base,
        dependentArgs: { account: "second" },
      }).queryKey
    ).not.toEqual(first.queryKey)
    expect(
      entityReferenceHydrationQueryOptions({
        ...base,
        exactValues: [{ entity_id: "different-file" }],
      }).queryKey
    ).not.toEqual(first.queryKey)
    for (const identity of [
      { conversationId: "conversation-2" },
      { toolName: "other_tool" },
      { fieldKey: "other_field" },
    ]) {
      expect(entityReferenceHydrationQueryOptions({ ...base, ...identity }).queryKey).not.toEqual(
        first.queryKey
      )
    }
    setActiveWorkspaceSlug("second-workspace")
    expect(entityReferenceHydrationQueryOptions(base).queryKey).not.toEqual(first.queryKey)
    setActiveWorkspaceSlug(null)
    const noDependencies = entityReferenceSearchQueryOptions({ ...base, dependsOn: [], search: "" })
    expect(noDependencies.queryKey).toContainEqual({})
    expect(JSON.stringify(noDependencies.queryKey)).not.toContain("PRIVATE_CONTENT")
    client.clear()
  })

  it("filters search payloads while preserving explicit null dependencies", async () => {
    const fetchStub = stubFetch(jsonResponse({ entity_kind: "file", choices: [] }))
    const client = new QueryClient()
    const query = entityReferenceSearchQueryOptions({
      conversationId: "conversation-1",
      toolName: "dependent_tool",
      fieldKey: "target",
      dependentArgs: { account: null, content: "PRIVATE_CONTENT" },
      dependsOn: ["account", "omitted"],
      search: "report",
    })
    await client.fetchInfiniteQuery(query)
    expect(getJsonRequestBody(getFetchRequest(fetchStub).init)).toMatchObject({
      dependent_args: { account: null },
      search: "report",
    })
    expect(JSON.stringify(query.queryKey)).not.toContain("PRIVATE_CONTENT")
    client.clear()
  })

  it("merges paged choices by identity", () => {
    const duplicate: EntityChoice = {
      identity: ["1", "file", "duplicate-id"],
      value: {
        version: 1,
        entity_kind: "file",
        entity_id: "duplicate-id",
        label: "Duplicate target",
      },
      label: "Duplicate target",
      description: null,
      scope_label: null,
    }
    const choices = mergeEntityChoices([], [{ choices: [duplicate] }, { choices: [duplicate] }])

    expect(choices).toEqual([duplicate])
  })

  it("isolates search generations and forwards TanStack Query cancellation", async () => {
    const fetchStub = stubFetch(
      jsonResponse({ entity_kind: "file", choices: [], next_cursor: null })
    )
    const base = {
      conversationId: "conversation-1",
      dependentArgs: {},
      fieldKey: "file_id",
      toolName: "read_file",
    }
    const first = entityReferenceSearchQueryOptions({ ...base, search: "first" })
    const second = entityReferenceSearchQueryOptions({ ...base, search: "second" })
    const signal = new AbortController().signal
    if (typeof second.queryFn !== "function") {
      throw new Error("Expected an entity search query function")
    }

    await second.queryFn({
      client: new QueryClient(),
      direction: "forward",
      meta: undefined,
      pageParam: "cursor-2",
      queryKey: second.queryKey,
      signal,
    })

    expect(first.queryKey).not.toEqual(second.queryKey)
    const { init, url } = getFetchRequest(fetchStub)
    expect(url.href).toBe(
      "http://localhost:8000/api/v1/tools/conversations/conversation-1/entity-references"
    )
    expect(init).toMatchObject({ credentials: "include", method: "POST", signal })
    expect(getJsonRequestBody(init)).toMatchObject({
      search: "second",
      cursor: "cursor-2",
    })
  })
})
