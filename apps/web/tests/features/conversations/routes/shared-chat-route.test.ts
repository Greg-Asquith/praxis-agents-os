import type * as ReactQuery from "@tanstack/react-query"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider, type QueryKey } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { SharedChatRoute } from "@/features/conversations/routes/shared-chat-route"
import type { Workspace } from "@/features/workspaces/types"
import { setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

const state = vi.hoisted(() => ({
  workspaceId: "11111111-1111-1111-1111-111111111111",
  conversationId: "22222222-2222-2222-2222-222222222222",
  workspace: null as Workspace | null,
  workspaces: [] as Workspace[],
  queries: [] as QueryKey[],
  data: null as {
    conversation: Record<string, unknown>
    transcript: Record<string, unknown>
  } | null,
}))
vi.mock("@tanstack/react-router", () => ({
  useParams: () => ({ workspaceId: state.workspaceId, conversationId: state.conversationId }),
  useNavigate: () => vi.fn(),
  Link: () => "Open my chats",
}))
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof ReactQuery>()),
  useInfiniteQuery: () => ({
    data: state.data ? { pages: [state.data.transcript] } : undefined,
    dataUpdatedAt: 1788969600000,
  }),
  useQuery: (options: { queryKey: QueryKey }) => {
    state.queries.push(options.queryKey)
    return { data: state.data?.conversation, dataUpdatedAt: 1788969600000 }
  },
}))
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({
    workspace: state.workspace,
    workspaces: state.workspaces,
    setWorkspaceBySlug: vi.fn(),
  }),
}))

const target: Workspace = {
  id: "11111111-1111-1111-1111-111111111111",
  slug: "renamed-workspace",
  name: "Team",
  icon_url: null,
  is_personal: false,
  status: "active",
  current_user_role: "read_only",
  created_at: "2026-09-09T12:00:00Z",
  updated_at: "2026-09-09T12:00:00Z",
  deleted: false,
  deleted_at: null,
}
const other: Workspace = { ...target, id: "33333333-3333-3333-3333-333333333333", slug: "other" }

function renderEntry() {
  const client = new QueryClient()
  const html = renderToStaticMarkup(
    createElement(QueryClientProvider, { client }, createElement(SharedChatRoute))
  )
  client.clear()
  return html
}

beforeEach(() => {
  state.workspaceId = target.id
  state.conversationId = "22222222-2222-2222-2222-222222222222"
  state.workspace = target
  state.workspaces = [target, other]
  state.queries = []
  state.data = null
  setActiveUserId("member")
  setActiveWorkspaceSlug(target.slug)
})

describe("shared entry membership gate", () => {
  it.each(["unknown", "removed", "inactive", "deleted workspace"])(
    "makes no chat query for %s access",
    (kind) => {
      if (kind === "unknown") state.workspaceId = "44444444-4444-4444-4444-444444444444"
      if (kind === "removed") state.workspaces = [{ ...target, current_user_role: null }]
      if (kind === "inactive") state.workspaces = [{ ...target, status: "suspended" }]
      if (kind === "deleted workspace") state.workspaces = [{ ...target, deleted: true }]
      expect(renderEntry()).toContain("Chat unavailable")
      expect(state.queries).toEqual([])
    }
  )

  it("waits for provider selection and resolves renamed workspaces by immutable ID", () => {
    state.workspace = other
    setActiveWorkspaceSlug(other.slug)
    expect(renderEntry()).toContain("Opening workspace")
    expect(state.queries).toEqual([])
    state.workspace = target
    setActiveWorkspaceSlug(target.slug)
    renderEntry()
    expect(state.queries).toEqual([
      ["conversations", "member", target.slug, state.conversationId, "detail"],
    ])
  })

  it("does not mount a second workspace viewer until navigation and selection agree", () => {
    renderEntry()
    state.queries = []
    state.workspaceId = other.id
    expect(renderEntry()).toContain("Opening workspace")
    expect(state.queries).toEqual([])
    state.workspace = other
    setActiveWorkspaceSlug(other.slug)
    renderEntry()
    expect(state.queries).toEqual([
      ["conversations", "member", other.slug, state.conversationId, "detail"],
    ])
  })
})

it.each([null, "Dana"])(
  "hides empty projected messages and explains viewing for owner %s",
  (ownerName) => {
    const messages = [
      {
        id: "hidden",
        conversation_id: state.conversationId,
        role: "system",
        sequence: 1,
        parts: { parts: [] },
        metadata: null,
        error: null,
        tool_name: null,
        client_message_id: null,
        created_at: "2026-09-09T12:00:00Z",
        updated_at: "2026-09-09T12:00:00Z",
      },
    ]
    state.data = {
      conversation: {
        access: "viewer",
        id: state.conversationId,
        workspace_id: target.id,
        title: "Shared chat",
        visibility: "workspace",
        owner_name: ownerName,
        agent_name: null,
        capabilities: { can_reply: false, can_manage_sharing: false, can_stop_sharing: false },
      },
      transcript: { access: "viewer", messages, total: 1, has_more: false },
    }
    const html = renderEntry()
    expect(html).toContain("Shared chat")
    expect(html).toContain("Only the chat owner can send messages.")
    expect(html).toContain("Later saved messages appear after refresh.")
    expect(html).toContain(ownerName ? "Shared by Dana" : "Shared with your workspace")
    expect(html).not.toContain("Empty message")
    expect(html).not.toContain("group/message")
    expect(messages).toHaveLength(1)
  }
)
