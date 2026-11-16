// apps/web/tests/integrations/outlook_calendar/presenters.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import { loadIntegrationUiModules } from "@/integrations/registry"

function render(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } })
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client }, createElement("div", null, node))
  )
}

const node = (content: string) => ({
  node: "praxis_untrusted",
  source_kind: "outlook_event",
  source_ref: "event",
  content,
})

function event(eventId: string, subject: string, start: string, timeZone: string) {
  return {
    reference: {
      version: 1,
      entity_kind: "outlook_event",
      calendar_id: "calendar",
      event_id: eventId,
      label: "Outlook event",
    },
    subject: node(subject),
    start,
    end: start.replace("T09", "T10"),
    time_zone: timeZone,
    is_all_day: false,
    location: node("Room 4"),
    organizer: { name: node("Dana"), address: node("dana@example.com") },
    attendee_count: 3,
    response_status: "accepted",
    show_as: "busy",
    sensitivity: "normal",
    is_online_meeting: true,
    join_url: null,
    type: "singleInstance",
    is_cancelled: false,
    web_link: node("https://outlook.example.com"),
  }
}

describe("Outlook Calendar event list", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["outlook_calendar"])
  })

  it("groups events by day and shows each event's time zone", () => {
    const row = renderCustomToolCallRow({
      activity: {
        id: "call",
        kind: "result",
        name: "outlook_calendar_list_events",
        args: { start: "2026-11-16T00:00:00", end: "2026-11-18T00:00:00" },
        status: "completed",
        result: {
          results: [
            {
              provider_key: "outlook_calendar",
              external_id: "calendar",
              display_name: "Calendar",
              status: "success",
              data: {
                events: [
                  event("first", "Planning", "2026-11-16T09:00:00", "Europe/London"),
                  event("second", "Review", "2026-11-17T09:00:00", "America/New_York"),
                ],
                count: 2,
                time_zone: "Europe/London",
              },
            },
          ],
        },
      },
      compact: false,
      defaultOpen: true,
      live: false,
      providerKey: "outlook_calendar",
      ui: null,
    })
    const html = render(row)
    expect(html).toContain("Planning")
    expect(html).toContain("Europe/London")
    expect(html).toContain("America/New York")
    expect(html.match(/<h4/g)).toHaveLength(2)
    expect(html).not.toMatch(/praxis_untrusted|source_ref/)
  })
})
