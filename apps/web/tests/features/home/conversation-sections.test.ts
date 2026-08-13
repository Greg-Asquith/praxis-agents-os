import { createElement, Fragment } from "react"
import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { agentsQueryKeys } from "@/features/agents/api/list-agents"
import type { AgentsListResponse } from "@/features/agents/types"
import type { Conversation } from "@/features/conversations/types"
import { RecentConversations } from "@/features/home/components/recent-conversations"
import { UnreadResults } from "@/features/home/components/unread-results"
import { renderHomeComponent } from "./test-utils"

describe("home conversation sections", () => {
  it("partitions unread results, recent work, and approval waits", () => {
    const conversations = [
      conversation({ id: "unread", title: "Unread result", unread: true }),
      conversation({ id: "read", title: "Read conversation" }),
      conversation({
        id: "approval",
        title: "Approval conversation",
        needs_approval: true,
        unread: true,
      }),
    ]
    const queryClient = new QueryClient()
    queryClient.setQueryData<AgentsListResponse>(
      agentsQueryKeys.list({ includeInactive: true, limit: 100 }),
      { agents: [], total: 0, limit: 100, offset: 0 }
    )
    const html = renderHomeComponent(
      createElement(
        Fragment,
        null,
        createElement(UnreadResults, { conversations }),
        createElement(RecentConversations, { conversations })
      ),
      queryClient
    )

    expect(html).toContain("Unread Conversations")
    expect(html).toContain("Unread result")
    expect(html).toContain("Continue Conversations")
    expect(html).toContain("Read conversation")
    expect(html).not.toContain("Approval conversation")
  })
})

function conversation(overrides: Partial<Conversation>): Conversation {
  return {
    id: "conversation",
    user_id: "user-1",
    workspace_id: "workspace-1",
    created_by: "user-1",
    title: "Conversation",
    description: null,
    status: "active",
    metadata: null,
    unread: false,
    source: "direct",
    last_message_at: "2026-07-28T08:00:00Z",
    active_agent_id: "agent-1",
    agent_slug: "agent",
    agent_name: "Agent",
    active_run_id: null,
    active_run_status: null,
    needs_approval: false,
    created_at: "2026-07-28T08:00:00Z",
    updated_at: "2026-07-28T08:00:00Z",
    ...overrides,
  }
}
