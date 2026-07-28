import { createElement } from "react"
import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { PendingApprovalsListResponse } from "@/features/conversations/types"
import { ApprovalsInbox } from "@/features/home/components/approvals-inbox"
import { renderHomeComponent } from "./test-utils"

describe("ApprovalsInbox", () => {
  it("renders tool and delegated approval context with overflow", () => {
    const queryClient = new QueryClient()
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
    expect(html).toContain("update_campaign")
    expect(html).toContain("via Budget specialist")
    expect(html).toContain("and 2 more")
  })

  it("renders the compact all-clear state", () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData<PendingApprovalsListResponse>(
      conversationsQueryKeys.pendingApprovals(),
      { items: [], total: 0 }
    )

    const html = renderHomeComponent(createElement(ApprovalsInbox), queryClient)

    expect(html).toContain("Nothing waiting for approval")
  })
})
