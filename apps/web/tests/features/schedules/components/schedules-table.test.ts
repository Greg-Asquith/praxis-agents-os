import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterContextProvider,
} from "@tanstack/react-router"
import { describe, expect, it } from "vitest"

import { SchedulesTable } from "@/features/schedules/components/schedules-table"
import type { AgentSchedule } from "@/features/schedules/types"
import type { Agent } from "@/features/agents/types"

const agent: Agent = {
  allowed_agent_ids: [],
  azure_deployment: null,
  created_at: "2026-08-12T08:00:00Z",
  created_by: "user-1",
  code_mode_enabled: false,
  deleted: false,
  deleted_at: null,
  description: null,
  id: "agent-1",
  instructions: "Run the report.",
  is_active: true,
  is_favorite: false,
  last_used_at: null,
  max_steps: null,
  metadata: null,
  model: null,
  model_provider: null,
  model_settings: null,
  name: "Reporting agent",
  skill_ids: [],
  slug: "reporting-agent",
  tool_names: [],
  tool_policies: null,
  updated_at: "2026-08-12T08:00:00Z",
  workspace_id: "workspace-1",
}

const schedule: AgentSchedule = {
  active_context: null,
  agent_id: agent.id,
  created_at: "2026-08-12T09:00:00Z",
  cron_expression: "0 9 * * 1",
  default_prompt: "Prepare the weekly report.",
  execution_params: null,
  health: "healthy",
  id: "schedule-1",
  interval_minutes: null,
  is_active: true,
  last_run_at: null,
  latest_run: null,
  name: "Weekly report",
  next_run_at: "2026-08-17T09:00:00Z",
  run_once_at: null,
  schedule_type: "cron",
  timezone: "Europe/London",
  updated_at: "2026-08-12T09:00:00Z",
  user_id: "user-1",
  workspace_id: "workspace-1",
}

describe("SchedulesTable", () => {
  it("renders app-table headers and the cell-heavy schedule row", () => {
    const html = renderSchedules([schedule])

    expect(html).toContain(">Name<")
    expect(html).toContain(">Cadence<")
    expect(html).toContain(">Status<")
    expect(html).toContain(">Next run<")
    expect(html).toContain(">Last run<")
    expect(html.match(/Weekly report/g)).toHaveLength(4)
    expect(html.match(/Reporting agent/g)).toHaveLength(2)
    expect(html).toContain("Healthy")
    expect(html).toContain('href="/schedules/schedule-1"')
    expect(html).toContain('aria-label="Turn off Weekly report"')
  })

  it("keeps the existing empty state", () => {
    const html = renderSchedules([])

    expect(html).toContain("No schedules yet")
    expect(html).toContain(
      "Create a schedule to run an agent on a cron, interval, or one-time cadence."
    )
    expect(html).not.toContain("<table")
  })
})

function renderSchedules(schedules: AgentSchedule[]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const rootRoute = createRootRoute()
  const newScheduleRoute = createRoute({ getParentRoute: () => rootRoute, path: "/schedules/new" })
  const scheduleRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/schedules/$scheduleId",
  })
  const router = createRouter({
    history: createMemoryHistory({ initialEntries: ["/"] }),
    routeTree: rootRoute.addChildren([newScheduleRoute, scheduleRoute]),
  })

  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(RouterContextProvider, {
        children: createElement(SchedulesTable, { agents: [agent], schedules }),
        router,
      })
    )
  )
}
