import { createElement } from "react"
import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { agentsQueryKeys } from "@/features/agents/api/list-agents"
import type { Agent, AgentsListResponse } from "@/features/agents/types"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { Conversation, PendingApprovalsListResponse } from "@/features/conversations/types"
import { AttentionQueue } from "@/features/home/components/attention-queue"
import { schedulesQueryKeys } from "@/features/schedules/api/list-schedules"
import type { AgentSchedule, SchedulesListResponse } from "@/features/schedules/types"
import { renderHomeComponent } from "./test-utils"

const QUERY_PARAMS = { includeInactive: true, limit: 100 }

describe("AttentionQueue", () => {
  it("renders the compact all-clear line", () => {
    const queryClient = seededClient({ approvals: [], schedules: [] })
    const html = renderHomeComponent(
      createElement(AttentionQueue, { conversations: [] }),
      queryClient
    )

    expect(html).toContain("Nothing needs your attention")
    expect(html).toContain("Schedules are healthy and every conversation is read")
    expect(html).not.toContain("Needs your attention")
  })

  it("renders one status badge for each attention kind", () => {
    const queryClient = seededClient({
      approvals: [approval],
      schedules: [failingSchedule],
    })
    const html = renderHomeComponent(
      createElement(AttentionQueue, {
        conversations: [conversation({ id: "unread", title: "Fresh result", unread: true })],
      }),
      queryClient
    )

    expect(html).toContain("Approve")
    expect(html).toContain("Schedule failing")
    expect(html).toContain("Unread")
  })

  it("caps the initial queue at eight items", () => {
    const queryClient = seededClient({ approvals: [], schedules: [] })
    const conversations = Array.from({ length: 10 }, (_, index) =>
      conversation({
        id: `unread-${String(index + 1)}`,
        title: `Unread result ${String(index + 1)}`,
        unread: true,
      })
    )
    const html = renderHomeComponent(createElement(AttentionQueue, { conversations }), queryClient)

    expect(html).toContain("Show 2 more")
    expect(html).toContain("Unread result 8")
    expect(html).not.toContain("Unread result 9")
  })

  it("keeps the approvals API total visible when the response is capped", () => {
    const queryClient = seededClient({
      approvalTotal: 3,
      approvals: [approval],
      schedules: [],
    })
    const html = renderHomeComponent(
      createElement(AttentionQueue, { conversations: [] }),
      queryClient
    )

    expect(html).toContain("and 2 more")
  })
})

function seededClient({
  approvalTotal,
  approvals,
  schedules,
}: {
  approvalTotal?: number
  approvals: PendingApprovalsListResponse["items"]
  schedules: AgentSchedule[]
}) {
  const queryClient = new QueryClient()
  queryClient.setQueryData<AgentsListResponse>(agentsQueryKeys.list(QUERY_PARAMS), {
    agents: [agent],
    total: 1,
    limit: 100,
    offset: 0,
  })
  queryClient.setQueryData<PendingApprovalsListResponse>(
    conversationsQueryKeys.pendingApprovals(),
    { items: approvals, total: approvalTotal ?? approvals.length }
  )
  queryClient.setQueryData<SchedulesListResponse>(schedulesQueryKeys.list(QUERY_PARAMS), {
    items: schedules,
    total: schedules.length,
    limit: 100,
    offset: 0,
  })
  return queryClient
}

const agent: Agent = {
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
  created_at: "2026-08-26T08:00:00Z",
  updated_at: "2026-08-26T08:00:00Z",
  deleted: false,
  deleted_at: null,
}

const approval: PendingApprovalsListResponse["items"][number] = {
  run_id: "run-1",
  conversation_id: "approval-conversation",
  conversation_title: "Campaign review",
  agent_id: "agent-1",
  agent_name: "Campaign operator",
  awaiting_since: "2026-08-26T08:00:00Z",
  pending_tool_names: ["update_campaign"],
  delegated_agent_names: [],
}

const failingSchedule: AgentSchedule = {
  id: "schedule-1",
  agent_id: "agent-1",
  user_id: "user-1",
  workspace_id: "workspace-1",
  name: "Campaign report",
  schedule_type: "interval",
  cron_expression: null,
  interval_minutes: 60,
  run_once_at: null,
  timezone: "Europe/London",
  default_prompt: "Prepare the campaign report.",
  execution_params: null,
  active_context: null,
  is_active: true,
  last_run_at: "2026-08-26T08:00:00Z",
  next_run_at: "2026-08-26T09:00:00Z",
  created_at: "2026-08-25T08:00:00Z",
  updated_at: "2026-08-26T08:00:00Z",
  health: "needs_attention",
  latest_run: {
    id: "schedule-run-1",
    schedule_id: "schedule-1",
    scheduled_for: "2026-08-26T08:00:00Z",
    status: "terminal_failed",
    attempt_count: 1,
    conversation_id: "schedule-conversation",
    agent_run_id: "agent-run-1",
    accepted_at: "2026-08-26T08:00:00Z",
    completed_at: null,
    failed_at: "2026-08-26T08:01:00Z",
    last_error_code: "provider_error",
    last_error_message: "Provider request failed.",
    outcome: "error",
    completion_json: null,
    created_at: "2026-08-26T08:00:00Z",
    health: "needs_attention",
  },
}

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
    last_message_at: "2026-08-26T08:00:00Z",
    active_agent_id: "agent-1",
    agent_slug: "campaign-operator",
    agent_name: "Campaign operator",
    active_run_id: null,
    active_run_status: null,
    needs_approval: false,
    created_at: "2026-08-26T08:00:00Z",
    updated_at: "2026-08-26T08:00:00Z",
    ...overrides,
  }
}
