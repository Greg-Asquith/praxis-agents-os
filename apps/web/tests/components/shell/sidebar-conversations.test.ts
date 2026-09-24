import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"

import { SidebarConversations } from "@/components/shell/sidebar-conversations"
import type { Conversation, SharedConversation } from "@/features/conversations/types"

vi.mock("@tanstack/react-router", () => ({
  Link: ({
    children,
    to,
    params,
    ...props
  }: {
    children: ReactNode
    to: string
    params?: Record<string, string>
  }) =>
    createElement(
      "a",
      { ...props, href: to.replace(/\$(\w+)/g, (_, key: string) => params?.[key] ?? "") },
      children
    ),
}))

const viewer: SharedConversation = {
  id: "shared",
  workspace_id: "team",
  title: "Team research",
  source: "direct",
  agent_name: "Research assistant",
  created_at: "2026-09-24T09:00:00Z",
  updated_at: "2026-09-24T09:00:00Z",
  last_message_at: null,
  active_run_status: null,
  access: "viewer",
  visibility: "workspace",
  owner_name: "Alex",
  capabilities: { can_reply: false, can_manage_sharing: false, can_stop_sharing: false },
}
const owner: Conversation = {
  ...viewer,
  id: "owned",
  access: "owner",
  title: "My research",
  user_id: "me",
  created_by: "me",
  description: null,
  status: "active",
  metadata: null,
  unread: true,
  active_agent_id: "agent",
  agent_slug: "research",
  active_run_id: "run",
  needs_approval: true,
}

it("links viewers to saved shared chats, shows the owner, and omits owner badges", () => {
  const html = renderToStaticMarkup(
    createElement(SidebarConversations, {
      conversations: [{ ...viewer, unread: true, needs_approval: true } as SharedConversation],
      pathname: "/shared-chats/team/shared",
    })
  )
  expect(html).toContain('href="/shared-chats/team/shared"')
  expect(html).toContain('aria-current="page"')
  expect(html).toContain("Alex")
  expect(html).not.toContain("Research assistant")
  expect(html).not.toContain('aria-label="Unread"')
  expect(html).not.toContain('aria-label="Needs approval"')
})

it("keeps the owner route, agent label, and badges", () => {
  const html = renderToStaticMarkup(
    createElement(SidebarConversations, {
      conversations: [owner],
      pathname: "/conversations/owned",
    })
  )
  expect(html).toContain('href="/conversations/owned"')
  expect(html).toContain('aria-current="page"')
  expect(html).toContain("Research assistant")
  expect(html).toContain('aria-label="Unread"')
  expect(html).toContain('aria-label="Needs approval"')
})

it("uses the shared audience fallback and leaves other rows unselected", () => {
  const html = renderToStaticMarkup(
    createElement(SidebarConversations, {
      conversations: [{ ...viewer, owner_name: null }],
      pathname: "/conversations/new",
    })
  )
  expect(html).toContain("Shared with your workspace")
  expect(html).not.toContain('aria-current="page"')
})
