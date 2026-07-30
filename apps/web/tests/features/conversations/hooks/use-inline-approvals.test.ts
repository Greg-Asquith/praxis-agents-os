import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { useInlineApprovals } from "@/features/conversations/hooks/use-inline-approvals"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { PendingToolApproval } from "@/features/conversations/types"

const approvals: PendingToolApproval[] = [
  {
    tool_call_id: "reused-call",
    name: "write_file",
    args: { name: "active.txt" },
  },
]

describe("useInlineApprovals", () => {
  it("only binds approval controls to the matching active run", () => {
    const html = renderToStaticMarkup(createElement(ApprovalBindingProbe))

    expect(html).toContain('data-active="bound"')
    expect(html).toContain('data-old="unbound"')
  })
})

function ApprovalBindingProbe() {
  const { resolveApprovalControls } = useInlineApprovals({
    activeRunId: "run-active",
    approvals,
    enabled: true,
    isSubmitting: false,
    onSubmit: () => Promise.resolve(),
  })

  const oldActivity = approvalActivity("run-old")
  const activeActivity = approvalActivity("run-active")

  return createElement("span", {
    "data-active": resolveApprovalControls(activeActivity) ? "bound" : "unbound",
    "data-old": resolveApprovalControls(oldActivity) ? "bound" : "unbound",
  })
}

function approvalActivity(agentRunId: string): ToolActivity {
  return {
    id: "reused-call",
    agentRunId,
    kind: "approval",
    status: "awaiting_approval",
    name: "write_file",
    args: { name: `${agentRunId}.txt` },
  }
}
