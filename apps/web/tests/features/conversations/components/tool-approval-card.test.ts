import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ToolApprovalCard } from "@/features/conversations/components/tool-approval-card"

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
        iconToken: "search",
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
        iconToken: "search",
        title: "Search the Web",
      })
    )

    expect(html).toContain("Approved")
    expect(html).toContain("Waiting for your decision on 1 more request.")
    expect(html).not.toContain("Requires Approval")
  })
})
