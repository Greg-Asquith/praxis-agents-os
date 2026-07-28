import { createElement } from "react"
import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { agentsQueryKeys } from "@/features/agents/api/list-agents"
import type { Agent, AgentsListResponse } from "@/features/agents/types"
import { AgentLauncher } from "@/features/home/components/agent-launcher"
import { renderHomeComponent } from "./test-utils"

const AGENT_PARAMS = { includeInactive: false, limit: 100 }

describe("AgentLauncher", () => {
  it("orders active agents by most recently used and puts never-used agents last", () => {
    const html = renderAgents([
      agent("never-used", "Never used", null),
      agent("recent", "Recently used", "2026-07-28T10:00:00Z"),
      agent("inactive", "Inactive", "2026-07-28T11:00:00Z", false),
      agent("older", "Used earlier", "2026-07-27T10:00:00Z"),
    ])

    expect(html).not.toContain("Inactive")
    expect(html.indexOf("Recently used")).toBeLessThan(html.indexOf("Used earlier"))
    expect(html.indexOf("Used earlier")).toBeLessThan(html.indexOf("Never used"))
  })
})

function renderAgents(agents: Agent[]): string {
  const queryClient = new QueryClient()
  queryClient.setQueryData<AgentsListResponse>(agentsQueryKeys.list(AGENT_PARAMS), {
    agents,
    limit: 100,
    offset: 0,
    total: agents.length,
  })
  return renderHomeComponent(createElement(AgentLauncher), queryClient)
}

function agent(id: string, name: string, lastUsedAt: string | null, isActive = true): Agent {
  return {
    id,
    name,
    slug: id,
    description: null,
    instructions: "Help the user.",
    workspace_id: "workspace-1",
    created_by: "user-1",
    tool_names: [],
    tool_policies: null,
    skill_ids: [],
    allowed_agent_ids: [],
    model_provider: null,
    model: null,
    model_settings: null,
    azure_deployment: null,
    max_steps: 20,
    is_active: isActive,
    is_favorite: false,
    last_used_at: lastUsedAt,
    metadata: null,
    created_at: "2026-07-27T08:00:00Z",
    updated_at: "2026-07-28T08:00:00Z",
    deleted: false,
    deleted_at: null,
  }
}
