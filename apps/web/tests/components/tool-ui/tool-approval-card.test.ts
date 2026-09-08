import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import {
  ToolApprovalCard,
  ToolApprovalDecisionCard,
  ToolApprovalLoadingCard,
} from "@/components/tool-ui/approval-card"

describe("ToolApprovalCard", () => {
  it("renders an undecided request as an always-open approval surface", () => {
    const html = renderToStaticMarkup(
      createElement(ToolApprovalCard, {
        children: createElement("input", {
          "aria-label": "Search query",
          defaultValue: "Praxis Agents",
        }),
        decision: "pending",
        footer: createElement("button", null, "Approve & Search"),
        prompt: "The agent wants to search the web.",
        title: "Search the Web",
      })
    )

    expect(html).toContain("Requires Approval")
    expect(html).toContain("Approve &amp; Search")
    expect(html).toContain("Praxis Agents")
    expect(html).not.toContain("<details")
  })

  it("communicates the locked approved state", () => {
    const html = renderToStaticMarkup(
      createElement(ToolApprovalCard, {
        children: createElement("p", null, "Query: Praxis Agents"),
        decision: "approved",
        footer: createElement("p", null, "Waiting for your decision on 1 more request."),
        title: "Search the Web",
      })
    )

    expect(html).toContain("Approved")
    expect(html).toContain("Waiting for your decision on 1 more request.")
    expect(html).not.toContain("Requires Approval")
  })

  it("offers decline alongside retry after a failed submit", () => {
    const html = renderToStaticMarkup(
      createElement(ToolApprovalDecisionCard, {
        activityId: "call-1",
        args: { query: "Microsoft invoice" },
        controls: {
          decision: { decision: "approved", edits: {}, message: "" },
          error: "This field must be on or off",
          onDecisionChange: () => undefined,
          onRetry: () => undefined,
          pendingCount: 0,
          submitting: false,
        },
        label: "Search Outlook messages",
        toolName: "outlook_mail_search_messages",
      })
    )

    expect(html).toContain("This field must be on or off")
    expect(html).toContain("Try Again")
    expect(html).toContain("Decline")
  })

  it("uses the approval-card structure while recovery details load", () => {
    const html = renderToStaticMarkup(createElement(ToolApprovalLoadingCard))

    expect(html).toContain("Preparing approval")
    expect(html).toContain("Requires Approval")
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain("Loading approval request")
  })
})
