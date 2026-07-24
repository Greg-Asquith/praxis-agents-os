import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ConversationDetailHeader } from "@/features/conversations/components/conversation-detail-header"
import type { Conversation } from "@/features/conversations/types"

const conversation: Conversation = {
  id: "conversation-1",
  user_id: "user-1",
  workspace_id: "workspace-1",
  created_by: "user-1",
  title: "Airtable update",
  description: null,
  status: "active",
  metadata: null,
  unread: true,
  source: "event",
  last_message_at: null,
  active_agent_id: "agent-1",
  agent_slug: "ops-agent",
  agent_name: "Ops agent",
  active_run_id: null,
  active_run_status: null,
  needs_approval: false,
  created_at: "2026-07-24T08:00:00Z",
  updated_at: "2026-07-24T08:00:00Z",
}

describe("ConversationDetailHeader", () => {
  it("identifies event-triggered conversations with accessible copy", () => {
    const html = renderToStaticMarkup(
      createElement(ConversationDetailHeader, {
        activeRun: null,
        conversation,
        scheduleLabel: null,
      })
    )

    expect(html).toContain("Triggered by an event")
  })
})
