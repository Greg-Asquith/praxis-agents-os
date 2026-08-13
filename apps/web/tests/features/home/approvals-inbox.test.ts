import { createElement } from "react"
import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { agentsQueryKeys } from "@/features/agents/api/list-agents"
import type { Agent, AgentsListResponse } from "@/features/agents/types"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { PendingApprovalsListResponse } from "@/features/conversations/types"
import { ApprovalsInbox } from "@/features/home/components/approvals-inbox"
import { renderHomeComponent } from "./test-utils"

const campaignAgent: Agent = {
  id: "agent-1",
  name: "Campaign operator",
  slug: "campaign-operator",
  description: null,
  instructions: "Operate campaigns.",
  workspace_id: "workspace-1",
  created_by: "user-1",
  code_mode_enabled: false,
  tool_names: [],
  tool_policies: null,
  skill_ids: [],
  allowed_agent_ids: [],
  model_provider: null,
  model: null,
  model_settings: null,
  azure_deployment: null,
  max_steps: null,
  is_active: true,
  is_favorite: false,
  last_used_at: null,
  metadata: { identity_color: 3 },
  created_at: "2026-07-01T10:00:00.000Z",
  updated_at: "2026-07-01T10:00:00.000Z",
  deleted: false,
  deleted_at: null,
}

function seedAgents(queryClient: QueryClient, agents: Agent[]) {
  queryClient.setQueryData<AgentsListResponse>(
    agentsQueryKeys.list({ includeInactive: true, limit: 100 }),
    { agents, total: agents.length, limit: 100, offset: 0 }
  )
}

describe("ApprovalsInbox", () => {
  it("renders tool and delegated approval context with overflow", () => {
    const queryClient = new QueryClient()
    seedAgents(queryClient, [campaignAgent])
    queryClient.setQueryData<PendingApprovalsListResponse>(
      conversationsQueryKeys.pendingApprovals(),
      {
        items: [
          {
            run_id: "run-1",
            conversation_id: "conversation-1",
            conversation_title: "Campaign review",
            agent_id: "agent-1",
            agent_name: "Campaign operator",
            awaiting_since: "2026-07-28T10:00:00Z",
            pending_tool_names: ["update_campaign"],
            delegated_agent_names: ["Budget specialist"],
          },
        ],
        total: 3,
      }
    )

    const html = renderHomeComponent(createElement(ApprovalsInbox), queryClient)

    expect(html).toContain("Campaign operator")
    expect(html).toContain("Campaign review")
    expect(html).toContain("Update Campaign")
    expect(html).toContain("rounded-md")
    expect(html).toContain("via Budget specialist")
    expect(html).toContain("and 2 more")
    expect(html).toContain("--agent-3")
  })

  it("renders the compact all-clear state", () => {
    const queryClient = new QueryClient()
    seedAgents(queryClient, [])
    queryClient.setQueryData<PendingApprovalsListResponse>(
      conversationsQueryKeys.pendingApprovals(),
      { items: [], total: 0 }
    )

    const html = renderHomeComponent(createElement(ApprovalsInbox), queryClient)

    expect(html).toContain("Nothing waiting for approval")
  })
})
