// apps/web/tests/integrations/outlook_calendar/calendar-approvals.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it, vi } from "vitest"

import type { ApprovalField } from "@/components/tool-ui/approval-card"
import { buildResumeDecisions } from "@/features/conversations/approval-decisions"
import { outlookCalendarCreateEventPresenter } from "@/integrations/outlook_calendar/presenters/create-event"
import { loadIntegrationUiModules } from "@/integrations/registry"
import { approvalIdentity } from "../../support/approvals"

function field(key: string, format: ApprovalField["format"], secondary = false): ApprovalField {
  return {
    key,
    label: key,
    format,
    secondary,
    editable: true,
    min_rows: 0,
    options: [],
    placeholder: "",
  }
}

const FIELDS = [
  field("subject", "text"),
  field("start", "datetime"),
  field("end", "datetime"),
  field("time_zone", "text"),
  field("attendees", "list"),
  field("is_online_meeting", "boolean", true),
]
const REPLAY = {
  subject: "Quarterly plan",
  start: "2026-11-18T09:00:00",
  end: "2026-11-18T10:00:00",
  attendees: ["dana@example.com"],
}
// The server shows the mailbox zone the write falls back to.
const DISPLAY = { ...REPLAY, time_zone: "GMT Standard Time" }

function render(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } })
  return renderToStaticMarkup(createElement(QueryClientProvider, { client }, node))
}

describe("Outlook Calendar approvals", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["outlook_calendar"])
  })

  it("submits the edited start, attendee list, and Teams option", () => {
    const attendees = ["kai@example.com", "lee@example.com"]
    const decisions = buildResumeDecisions(
      [
        {
          ...approvalIdentity("create"),
          tool_call_id: "create",
          name: "outlook_calendar_create_event",
          args: DISPLAY,
          replay_args: REPLAY,
        },
      ],
      {
        create: {
          decision: "approved",
          edits: { start: "2026-11-18T14:30", attendees, is_online_meeting: true },
          message: "",
        },
      },
      () => FIELDS
    )
    expect(decisions).toEqual([
      {
        approval_id: "create",
        tool_call_id: "create",
        decision: "approved",
        override_args: {
          ...REPLAY,
          start: "2026-11-18T14:30",
          attendees,
          is_online_meeting: true,
        },
      },
    ])
  })

  it.each([
    [false, false],
    [true, true],
  ])("shows the calendar picker only when there is a choice (%s)", (choice, shown) => {
    const calendar = { ...field("calendar", "entity", true), entity_kind: "outlook_calendar" }
    const html = render(
      outlookCalendarCreateEventPresenter.render({
        activity: {
          id: "create",
          kind: "call",
          name: "outlook_calendar_create_event",
          status: "awaiting_approval",
          args: { ...DISPLAY, calendar: null, _calendar_choice: choice },
        },
        approvalDecision: {
          decision: { decision: "pending", edits: {}, message: "" },
          disabled: false,
          error: null,
          onDecisionChange: vi.fn(),
          onRetry: vi.fn(),
          pendingCount: 1,
          submitting: false,
        },
        compact: false,
        defaultOpen: true,
        live: false,
        providerKey: "outlook_calendar",
        ui: {
          icon: "outlook_calendar",
          running_label: "",
          completed_label: "",
          failed_label: "",
          approval_title: "",
          approval_prompt: "",
          approve_label: "",
          arg_fields: [...FIELDS, calendar],
          result_fields: [],
        },
      })
    )
    expect(html.includes("Add calendar")).toBe(shown)
  })
})
