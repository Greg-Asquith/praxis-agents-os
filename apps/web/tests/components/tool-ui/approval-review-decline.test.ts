import { createElement, useState, type MouseEvent } from "react"
import type * as ReactModule from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  ToolApprovalDecisionCard,
  type ApprovalDecision,
  type ToolApprovalDecisionControls,
} from "@/components/tool-ui/approval-card"
import { Button } from "@/components/ui/button"

vi.mock("react", async (original) => {
  const module = await original<typeof ReactModule>()
  return { ...module, useState: vi.fn(module.useState) }
})
vi.mock("@/components/ui/button", async (original) => {
  const module = await original<{ Button: typeof Button }>()
  return { ...module, Button: vi.fn(module.Button) }
})

function render(controls: ToolApprovalDecisionControls) {
  return renderToStaticMarkup(
    createElement(ToolApprovalDecisionCard, {
      activityId: "call",
      args: {},
      controls,
      label: "Save SharePoint file",
      toolName: "sharepoint_write_file",
    })
  )
}

function click(label: string) {
  const props = vi.mocked(Button).mock.calls.find(([value]) => value.children === label)?.[0]
  if (!props?.onClick) throw new Error(`Missing action: ${label}`)
  props.onClick({
    ...({ type: "click" } as MouseEvent<HTMLButtonElement>),
    preventBaseUIHandler: vi.fn(),
  })
}

beforeEach(() => vi.clearAllMocks())

describe("declining after approval review fails", () => {
  it.each(["pending", "approved"] as const)(
    "clears the error and lets a %s request reach decline confirmation",
    (decision) => {
      const controls: ToolApprovalDecisionControls = {
        decision: { decision, edits: { source: null }, message: "" },
        error: "The selected File is unavailable.",
        onDecisionChange: vi.fn((next: ApprovalDecision) => {
          controls.decision = next
          controls.error = null
        }),
        onRetry: vi.fn(),
        pendingCount: 1,
        submitting: false,
      }
      expect(render(controls)).toContain("Try Again")
      click("Decline")
      expect(controls.onDecisionChange).toHaveBeenCalledWith({
        decision: "pending",
        edits: { source: null },
        message: "",
      })
      vi.mocked(Button).mockClear()
      vi.mocked(useState).mockImplementationOnce(() => [true, vi.fn()])
      const html = render(controls)
      expect(html).toContain("Decline Request")
      expect(html).not.toContain("Try Again")
      click("Decline Request")
      expect(controls.onDecisionChange).toHaveBeenLastCalledWith({
        decision: "denied",
        edits: {},
        message: "",
      })
      expect(controls.onRetry).not.toHaveBeenCalled()
    }
  )
})
