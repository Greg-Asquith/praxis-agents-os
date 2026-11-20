// apps/web/tests/features/memories/routes/memories-route.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"

import { MemoriesRoute } from "@/features/memories/routes/memories-route"
import type { Memory } from "@/features/memories/types"

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: { children: ReactNode }) => createElement("a", null, children),
}))
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (value: unknown) => value,
  useSuspenseQuery: () => ({ data: { id: "viewer-1" } }),
  useMutation: () => ({ isPending: false, error: null, mutate: vi.fn() }),
  useQueryClient: () => ({}),
}))
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({
    workspace: {
      id: "workspace-1",
      is_personal: false,
      current_user_role: "owner",
      memory_recall_enabled: true,
    },
  }),
}))
vi.mock("@/features/agents/api/list-agents", () => ({
  useAgentsQuery: () => ({ data: { agents: [] } }),
}))
vi.mock("@/features/memories/api/list-memories", () => ({
  useMemoriesQuery: () => ({
    data: {
      memories: [memory()],
      audience_counts: { shared: 1, private: 0 },
      total: 1,
      limit: 50,
      offset: 0,
    },
  }),
}))

it("renders a learned memory a person later edited as the person's", () => {
  const html = renderToStaticMarkup(createElement(MemoriesRoute))

  expect(html).toContain("Invoices go out on the 1st")
  expect(html).toContain("Edited by You")
})

function memory(): Memory {
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
    created_by: "user",
    created_by_user_id: "viewer-1",
    expires_at: null,
    superseded_by_id: null,
    archived_at: null,
    archive_reason: null,
    recall_disabled_at: null,
    last_edited_by_user_at: "2026-11-20T09:00:00Z",
    source_conversation_id: null,
    source_conversation_title: null,
    created_at: "2026-11-19T09:00:00Z",
    updated_at: "2026-11-20T09:00:00Z",
  }
}
