// apps/web/tests/features/conversations/memory-tools.test.ts

import { describe, expect, it } from "vitest"

import {
  forgetMemoryResult,
  saveMemoryResult,
  saveMemoryTitleArg,
  searchMemoryQueryArg,
  searchMemoryResult,
  updateMemoryResult,
} from "@/features/conversations/native-tools/memory-tools"

describe("save_memory results", () => {
  it("parses created and reinforced saves", () => {
    const created = saveMemoryResult({
      status: "created",
      memory: memorySummary(),
      similarity: null,
    })
    const reinforced = saveMemoryResult({
      status: "reinforced",
      memory: memorySummary(),
      similarity: 0.91,
    })

    expect(created?.status).toBe("created")
    expect(created && "memory" in created ? created.memory.title : null).toBe(
      "Prefers concise replies"
    )
    expect(reinforced?.status).toBe("reinforced")
    expect(reinforced && "similarity" in reinforced ? reinforced.similarity : null).toBe(0.91)
  })

  it("parses near duplicates with and without the existing memory", () => {
    const withExisting = saveMemoryResult({
      status: "near_duplicate",
      existing_memory: memorySummary(),
      similarity: 0.95,
      next_step: "For a true duplicate, call save_memory again with duplicate_of set.",
    })
    const withoutExisting = saveMemoryResult({
      status: "near_duplicate",
      existing_memory: null,
      similarity: 0.95,
    })

    expect(withExisting?.status).toBe("near_duplicate")
    expect(
      withExisting && "existing_memory" in withExisting ? withExisting.existing_memory?.title : null
    ).toBe("Prefers concise replies")
    expect(
      withoutExisting && "existing_memory" in withoutExisting
        ? withoutExisting.existing_memory
        : undefined
    ).toBeNull()
  })

  it("unwraps return_value envelopes and rejects malformed payloads", () => {
    const result = saveMemoryResult({
      return_value: { status: "created", memory: memorySummary(), similarity: null },
    })

    expect(result?.status).toBe("created")
    expect(saveMemoryResult({ status: "created", memory: { id: "m-1" } })).toBeNull()
    expect(saveMemoryResult({ status: "deleted", memory: memorySummary() })).toBeNull()
    expect(
      saveMemoryResult({ status: "created", memory: { ...memorySummary(), scope: "galaxy" } })
    ).toBeNull()
    expect(saveMemoryResult("plain text")).toBeNull()
  })
})

describe("search_memory results", () => {
  it("parses hits and search metadata", () => {
    const result = searchMemoryResult({
      query: "reply style",
      results: [searchHit()],
      total: 1,
      matches_found: 4,
      results_truncated: true,
      used_lexical_fallback: false,
      next_step: "Search again with narrower terms.",
    })

    expect(result).not.toBeNull()
    expect(result?.results[0]?.title).toBe("Prefers concise replies")
    expect(result?.matches_found).toBe(4)
    expect(result?.results_truncated).toBe(true)
  })

  it("rejects payloads with malformed hits", () => {
    expect(
      searchMemoryResult({
        query: "reply style",
        results: [{ ...searchHit(), kind: "mystery" }],
        total: 1,
        matches_found: 1,
        results_truncated: false,
        used_lexical_fallback: false,
      })
    ).toBeNull()
    expect(searchMemoryResult({ query: "reply style", results: [] })).toBeNull()
  })
})

describe("update_memory results", () => {
  it("parses updates and supersessions", () => {
    const updated = updateMemoryResult({
      status: "updated",
      memory: memorySummary(),
      superseded_memory_id: null,
    })
    const superseded = updateMemoryResult({
      status: "superseded",
      memory: memorySummary(),
      superseded_memory_id: "m-0",
    })

    expect(updated?.status).toBe("updated")
    expect(updated?.superseded_memory_id).toBeNull()
    expect(superseded?.superseded_memory_id).toBe("m-0")
    expect(updateMemoryResult({ status: "updated", memory: {} })).toBeNull()
  })
})

describe("forget_memory results", () => {
  it("parses archived and already-archived outcomes", () => {
    const archived = forgetMemoryResult({ status: "archived", memory: memorySummary() })
    const repeat = forgetMemoryResult({ status: "already_archived", memory: memorySummary() })

    expect(archived?.status).toBe("archived")
    expect(repeat?.status).toBe("already_archived")
    expect(forgetMemoryResult({ status: "deleted", memory: memorySummary() })).toBeNull()
  })
})

describe("memory tool args", () => {
  it("reads trimmed values from object and JSON string args", () => {
    expect(saveMemoryTitleArg({ title: "  Prefers concise replies  " })).toBe(
      "Prefers concise replies"
    )
    expect(searchMemoryQueryArg('{"query": "reply style"}')).toBe("reply style")
    expect(saveMemoryTitleArg({ title: "   " })).toBeNull()
    expect(searchMemoryQueryArg(undefined)).toBeNull()
  })
})

function memorySummary() {
  return {
    id: "m-1",
    scope: "user",
    kind: "note",
    memory_type: "preference",
    title: "Prefers concise replies",
    importance: 3,
    confidence: 0.8,
    status: "active",
  }
}

function searchHit() {
  return {
    id: "m-1",
    scope: "user",
    kind: "note",
    memory_type: "preference",
    title: "Prefers concise replies",
    content: "## Style\n\nKeep replies **short**.",
    content_truncated: false,
    source: "interactive",
    created_by: "agent",
    created_by_user_id: null,
    effective_confidence: 0.8,
    score: 0.72,
  }
}
