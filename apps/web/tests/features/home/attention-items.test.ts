import { describe, expect, it } from "vitest"

import type { Agent } from "@/features/agents/types"
import type { Conversation, PendingApprovalsListResponse } from "@/features/conversations/types"
import { buildAttentionItems } from "@/features/home/attention-items"
import type { AgentSchedule, ScheduleHealth } from "@/features/schedules/types"

describe("buildAttentionItems", () => {
  it("ranks and formats actionable items", () => {
    const approvals: PendingApprovalsListResponse = {
      items: [
        {
          run_id: "run-1",
          conversation_id: "approval-conversation",
          conversation_title: "Campaign review",
          agent_id: "agent-1",
          agent_name: "Campaign operator",
          awaiting_since: "2026-08-26T08:00:00Z",
          pending_tool_names: ["update_campaign"],
          delegated_agent_names: ["Budget specialist"],
        },
      ],
      total: 1,
    }
    const items = buildAttentionItems({
      approvals,
      schedules: [
        schedule("healthy", "Healthy digest"),
        schedule("retrying", "Retrying digest"),
        schedule("needs_attention", "Broken digest"),
      ],
      conversations: [
        conversation({ id: "unread", title: "Unread result", unread: true }),
        conversation({ id: "read", title: "Read result" }),
        conversation({
          id: "approval",
          title: "Approval result",
          needs_approval: true,
          unread: true,
        }),
      ],
      agentsById: new Map([[agent.id, agent]]),
    })

    expect(items.map((item) => item.kind)).toEqual(["approval", "schedule", "schedule", "unread"])
    expect(items.map((item) => item.title)).toEqual([
      "Campaign review",
      "Retrying digest",
      "Broken digest",
      "Unread result",
    ])
    expect(items[0]?.subtitle).toBe(
      "Campaign operator wants to run Update Campaign via Budget specialist"
    )
    expect(items[1]?.subtitle).toBe("Email agent · Send the latest digest.")
    expect(items[2]).toMatchObject({ errorMessage: "Provider request failed." })
    expect(items[3]?.subtitle).toBe("Email agent")
  })
})

const agent: Agent = {
  id: "agent-1",
  name: "Email agent",
  slug: "email-agent",
  description: null,
  instructions: "Send email.",
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
  metadata: null,
  created_at: "2026-08-26T08:00:00Z",
  updated_at: "2026-08-26T08:00:00Z",
  deleted: false,
  deleted_at: null,
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
    agent_slug: "email-agent",
    agent_name: "Email agent",
    active_run_id: null,
    active_run_status: null,
    needs_approval: false,
    created_at: "2026-08-26T08:00:00Z",
    updated_at: "2026-08-26T08:00:00Z",
    ...overrides,
  }
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
    last_run_at: "2026-08-26T08:00:00Z",
    next_run_at: "2026-08-26T09:00:00Z",
    created_at: "2026-08-25T08:00:00Z",
    updated_at: "2026-08-26T08:00:00Z",
    health,
    latest_run: {
      id: `${health}-run`,
      schedule_id: `${health}-schedule`,
      scheduled_for: "2026-08-26T08:00:00Z",
      status: health === "retrying" ? "retryable_failed" : "terminal_failed",
      attempt_count: 1,
      conversation_id: `${health}-conversation`,
      agent_run_id: `${health}-agent-run`,
      accepted_at: "2026-08-26T08:00:00Z",
      completed_at: null,
      failed_at: "2026-08-26T08:01:00Z",
      last_error_code: "provider_error",
      last_error_message: "Provider request failed.",
      outcome: health === "needs_attention" ? "error" : null,
      completion_json: null,
      created_at: "2026-08-26T08:00:00Z",
      health,
    },
  }
}
