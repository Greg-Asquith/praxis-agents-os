import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { AuditEventsTable } from "@/features/audit/components/audit-events-table"
import type { AuditEvent } from "@/features/audit/types"

const event: AuditEvent = {
  action: "tool_call_completed",
  actor_display: "Ada Operator",
  actor_id: "user-1",
  actor_type: "user",
  actor_user_id: "user-1",
  created_at: "2026-08-12T10:00:00Z",
  detail_event_id: "detail-1",
  details: {},
  id: "event-1",
  ip_address: "127.0.0.1",
  occurred_at: "2026-08-12T10:00:00Z",
  request_id: "request-1",
  requested_by_user_id: "user-1",
  resource_id: "call-1",
  resource_type: "tool_call",
  status: "success",
  summary: "Completed a tool call",
  tool_name: "read_file",
  tool_provider: "praxis",
  user_agent: "test",
  workspace_id: "workspace-1",
}

describe("AuditEventsTable", () => {
  it("renders server pagination through the app-table caption", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const html = renderToStaticMarkup(
      createElement(QueryClientProvider, {
        client: queryClient,
        children: createElement(AuditEventsTable, {
          events: [event],
          isFetching: false,
          limit: 50,
          offset: 50,
          onPageChange: () => undefined,
          onSelectEvent: () => undefined,
          total: 75,
        }),
      })
    )

    expect(html).toContain("Showing 51-75 of 75")
    expect(html).toContain('aria-label="Audit events pagination"')
    expect(html).toContain("Completed a tool call")
  })
})
