// apps/web/tests/features/memories/components/memory-display.test.ts

import { expect, it } from "vitest"

import { memoryOriginLabel } from "@/features/memories/components/memory-display"
import {
  DEFAULT_MEMORY_FILTERS,
  memoryListParams,
} from "@/features/memories/components/memory-filters"
import type { Memory } from "@/features/memories/types"

const viewer = { userId: "viewer-1", isPersonalWorkspace: false }

it("names a person's edit over how the memory began, and whose edit it was", () => {
  const edited = { last_edited_by_user_at: "2026-11-20T09:00:00Z" }

  expect(memoryOriginLabel(memory({}), viewer)).toBe("Learned Automatically")
  expect(memoryOriginLabel(memory(edited), viewer)).toBe("Edited by Your Team")
  expect(memoryOriginLabel(memory({ ...edited, scope: "user" }), viewer)).toBe("Edited by You")
  expect(
    memoryOriginLabel(memory({ created_by: "user", created_by_user_id: "viewer-1" }), viewer)
  ).toBe("Edited by You")
})

it("drops the agent filter on the Private tab and caps the search text", () => {
  const filters = { ...DEFAULT_MEMORY_FILTERS, agentId: "agent-1", q: "x".repeat(250) }

  expect(memoryListParams(filters, 0).agentId).toBe("agent-1")
  expect(memoryListParams({ ...filters, audience: "private" }, 0).agentId).toBeUndefined()
  expect(memoryListParams(filters, 0).q).toHaveLength(200)
})

function memory(overrides: Partial<Memory>): Memory {
  return {
    id: "memory-1",
    scope: "workspace",
    memory_type: "fact",
    status: "active",
    title: "Invoices go out on the 1st",
    content_md: "Finance sends every invoice on the first working day.",
    importance: 3,
    confidence: 0.8,
    effective_confidence: 0.8,
    agent_id: null,
    agent_name: null,
    user_id: null,
    source: "dream",
    created_by: "system",
    created_by_user_id: null,
    expires_at: null,
    superseded_by_id: null,
    archived_at: null,
    archive_reason: null,
    recall_disabled_at: null,
    last_edited_by_user_at: null,
    source_conversation_id: null,
    source_conversation_title: null,
    created_at: "2026-11-19T09:00:00Z",
    updated_at: "2026-11-20T09:00:00Z",
    ...overrides,
  }
}
