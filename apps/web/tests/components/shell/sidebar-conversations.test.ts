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
  user_id: "me",
  created_by: "me",
  description: null,
  status: "active",
  metadata: null,
  unread: false,
  active_agent_id: "agent",
  agent_slug: "research",
  active_run_id: null,
  needs_approval: false,
}

it("links viewer rows to the shared chat route and owner rows to the owner route", () => {
  const html = renderToStaticMarkup(
    createElement(SidebarConversations, {
      conversations: [viewer, owner],
      pathname: "/shared-chats/team/shared",
    })
  )

  expect(html).toMatch(/<a aria-current="page"[^>]*href="\/shared-chats\/team\/shared"/)
  expect(html).toContain('href="/conversations/owned"')
  expect(html).not.toContain('href="/conversations/shared"')
})
