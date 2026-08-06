import { createElement } from "react"
import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { agentsQueryKeys } from "@/features/agents/api/list-agents"
import type { AgentsListResponse } from "@/features/agents/types"
import { ScheduleAttention } from "@/features/home/components/schedule-attention"
import { schedulesQueryKeys } from "@/features/schedules/api/list-schedules"
import type {
  AgentSchedule,
  ScheduleHealth,
  SchedulesListResponse,
} from "@/features/schedules/types"
import { renderHomeComponent } from "./test-utils"

const SCHEDULE_PARAMS = { includeInactive: true, limit: 100 }
const AGENT_PARAMS = { includeInactive: true, limit: 100 }

describe("ScheduleAttention", () => {
  it("renders only failing and retrying schedules", () => {
    const html = renderSchedules([
      schedule("healthy", "Healthy digest"),
      schedule("retrying", "Retrying digest"),
      schedule("needs_attention", "Broken digest"),
    ])

    expect(html).not.toContain("Healthy digest")
    expect(html).toContain("Retrying digest")
    expect(html).toContain("Broken digest")
    expect(html).toContain("Email agent")
  })

  it("collapses when every schedule is healthy", () => {
    expect(renderSchedules([schedule("healthy", "Healthy digest")])).toBe("")
  })
})

function renderSchedules(schedules: AgentSchedule[]): string {
  const queryClient = new QueryClient()
  queryClient.setQueryData<SchedulesListResponse>(schedulesQueryKeys.list(SCHEDULE_PARAMS), {
    items: schedules,
    limit: 100,
    offset: 0,
    total: schedules.length,
  })
  queryClient.setQueryData<AgentsListResponse>(agentsQueryKeys.list(AGENT_PARAMS), {
    agents: [
      {
        id: "agent-1",
        name: "Email agent",
        slug: "email-agent",
        description: "Sends the daily digest.",
        instructions: "Send the digest.",
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
        is_active: true,
        is_favorite: false,
        last_used_at: null,
        metadata: null,
        created_at: "2026-07-28T08:00:00Z",
        updated_at: "2026-07-28T08:00:00Z",
        deleted: false,
        deleted_at: null,
      },
    ],
    limit: 100,
    offset: 0,
    total: 1,
  })
  return renderHomeComponent(createElement(ScheduleAttention), queryClient)
}

function schedule(health: ScheduleHealth, name: string): AgentSchedule {
  return {
    id: `${health}-schedule`,
    agent_id: "agent-1",
    user_id: "user-1",
    workspace_id: "workspace-1",
    name,
    schedule_type: "interval",
    cron_expression: null,
    interval_minutes: 60,
    run_once_at: null,
    timezone: "Europe/London",
    default_prompt: "Send the latest digest.",
    execution_params: null,
    active_context: null,
    is_active: true,
    last_run_at: "2026-07-28T08:00:00Z",
    next_run_at: "2026-07-28T09:00:00Z",
    created_at: "2026-07-27T08:00:00Z",
    updated_at: "2026-07-28T08:00:00Z",
    health,
    latest_run: {
      id: `${health}-run`,
      schedule_id: `${health}-schedule`,
      scheduled_for: "2026-07-28T08:00:00Z",
      status: health === "retrying" ? "retryable_failed" : "terminal_failed",
      attempt_count: 1,
      conversation_id: `${health}-conversation`,
      agent_run_id: `${health}-agent-run`,
      accepted_at: "2026-07-28T08:00:00Z",
      completed_at: null,
      failed_at: "2026-07-28T08:01:00Z",
      last_error_code: "provider_error",
      last_error_message: "Provider request failed.",
      outcome: health === "needs_attention" ? "error" : null,
      completion_json: health === "needs_attention" ? { error_code: "provider_error" } : null,
      created_at: "2026-07-28T08:00:00Z",
      health,
    },
  }
}
