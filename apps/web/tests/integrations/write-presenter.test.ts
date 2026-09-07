import { createElement, isValidElement, type ComponentProps, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import {
  ToolApprovalDecisionCard,
  type ToolApprovalDecisionControls,
} from "@/components/tool-ui/approval-card"
import type { ToolRowPresenterProps } from "@/integrations/contract"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
  type IntegrationWriteProvider,
  type IntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { isRecord } from "@/lib/guards"

type Args = { name: string }
const provider: IntegrationWriteProvider = {
  contextLabel: "Project",
  externalLabel: "Project code",
  fallbackDisplayName: "Selected project",
  providerKey: "example",
  formatContextValue: (value) => `Project ${value}`,
  renderHeading: (heading) => createElement("strong", null, "Example: ", heading),
  renderIcon: () => createElement("span", null, "Example icon"),
}
const variant: IntegrationWriteVariant<Args, string> = {
  approval: {
    approveLabel: "Approve change",
    label: "Change project",
    parseArgs,
    prompt: (args) => `Change ${args.name}`,
    title: (args) => `Review ${args.name}`,
    renderSummary: (value) => createElement("span", null, "Summary: ", parseArgs(value)?.name),
  },
  deniedDescription: "Change declined. Nothing changed.",
  emptyLabel: "No projects",
  failedDescription: "No change confirmed",
  heading: "Change project",
  malformedDescription: "Invalid project evidence",
  parseResult: (value) => (typeof value === "string" ? value : null),
  progressLabel: (args) => `Changing ${args?.name ?? "project"}`,
  renderOutcome: (result) => createElement("span", null, "Outcome: ", result),
  resultAriaLabel: "Project outcomes",
  resultFailure: "Missing project results",
  unconfirmedAriaLabel: "Unconfirmed projects",
  unverifiedDescription: "Check the project before retrying",
  waitingLabel: "Waiting for project approval",
  details: (args) => (args ? [{ label: "Requested", value: args.name }] : []),
}
function parseArgs(value: unknown): Args | null {
  return isRecord(value) && typeof value["name"] === "string" ? { name: value["name"] } : null
}
function controls(): ToolApprovalDecisionControls {
  return {
    decision: { decision: "pending", edits: {}, message: "" },
    disabled: false,
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    pendingCount: 1,
    submitting: false,
  }
}
function props(
  status: ToolRowPresenterProps["activity"]["status"] = "completed"
): ToolRowPresenterProps {
  return {
    activity: {
      id: "change-1",
      kind: "call",
      name: "change_project",
      status,
      args: { name: "Original" },
    },
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "ignored-context-provider",
  }
}
function entry(data: unknown, overrides: Record<string, unknown> = {}) {
  return {
    provider_key: "example",
    display_name: "Example project",
    external_id: "123",
    status: "success",
    data,
    error_code: null,
    error_message: null,
    ...overrides,
  }
}
function render(context: ToolRowPresenterProps, config = variant) {
  return renderToStaticMarkup(
    createElement("div", null, defineIntegrationWriteVariant(provider, config)(context))
  )
}
function approval(context: ToolRowPresenterProps, config = variant) {
  const node = defineIntegrationWriteVariant(provider, config)(context)
  if (
    !isValidElement<ComponentProps<typeof ToolApprovalDecisionCard>>(node) ||
    node.type !== ToolApprovalDecisionCard
  ) {
    throw new Error("Expected an approval card")
  }
  return node.props
}

describe("integration write presenter", () => {
  it("fails closed on malformed retained arguments even when edits would repair them", () => {
    const context = props("awaiting_approval")
    context.activity.args = null
    context.approvalDecision = controls()
    context.approvalDecision.decision.edits = { name: "Repair" }
    const card = approval(context)
    expect(card.validationError).toBe(
      "Decline this request, then ask the agent to prepare the action again."
    )
    expect(card.children).toBeUndefined()
    expect(render(context)).toContain("this action can&#x27;t be approved")
  })

  it("uses merged edits for validation, copy, and summary while retaining original execution arguments", () => {
    const context = props("awaiting_approval")
    context.approvalDecision = controls()
    context.approvalDecision.decision.edits = { name: "Edited" }
    const validate = vi.fn(() => null)
    const config = { ...variant, approval: { ...variant.approval, validateArgs: validate } }
    const card = approval(context, config)
    expect(card.args).toBe(context.activity.args)
    expect(card.controls).toBe(context.approvalDecision)
    expect(validate).toHaveBeenCalledWith({ name: "Edited" })
    expect(card.title).toBe("Review Edited")
    expect(card.prompt).toBe("Change Edited")
    expect(render(context, config)).toContain("Summary: Edited")
  })

  it("prioritizes display errors and suppresses provider validation and summary", () => {
    const context = props("awaiting_approval")
    context.activity.args = { name: "Original", _approval_display_error: "private diagnostics" }
    context.approvalDecision = controls()
    const validate = vi.fn(() => "Provider error")
    const summary = vi.fn(() => "Summary")
    const card = approval(context, {
      ...variant,
      approval: { ...variant.approval, validateArgs: validate, renderSummary: summary },
    })
    expect(card.validationError).toContain("Approval details are unavailable")
    expect(validate).not.toHaveBeenCalled()
    expect(summary).not.toHaveBeenCalled()
    expect(card.children).toBeNull()
  })

  it.each([null, { name: "Original" }])(
    "passes untrusted provenance through valid and invalid approvals",
    (args) => {
      const context = props("awaiting_approval")
      context.activity.args = args
      context.activity.derivedFromUntrusted = true
      context.activity.taintSources = [{ source_kind: "integration", source_ref: "page" }]
      context.approvalDecision = controls()
      const card = approval(context)
      expect(card.derivedFromUntrusted).toBe(true)
      expect(card.taintSources).toBe(context.activity.taintSources)
    }
  )

  it("blocks malformed edits even without a provider validator", () => {
    const context = props("awaiting_approval")
    context.approvalDecision = controls()
    context.approvalDecision.decision.edits = { name: [] }
    expect(approval(context).validationError).toContain("edited approval details are invalid")
  })

  it.each([false, true])(
    "keeps invalid drafts mounted only when configured (%s)",
    (renderInvalidDraft) => {
      const context = props("awaiting_approval")
      context.approvalDecision = controls()
      const summary = vi.fn(() => "Editable draft")
      const card = approval(context, {
        ...variant,
        approval: {
          ...variant.approval,
          renderInvalidDraft,
          validateArgs: () => "Correct the draft",
          renderSummary: summary,
        },
      })
      expect(card.validationError).toBe("Correct the draft")
      expect(summary).toHaveBeenCalledTimes(renderInvalidDraft ? 1 : 0)
    }
  )

  it.each(["enabled", "disabled", "submitting"])(
    "preserves custom field edits and locks (%s)",
    (state) => {
      const context = props("awaiting_approval")
      const decision = controls()
      context.approvalDecision = decision
      decision.disabled = state === "disabled"
      decision.submitting = state === "submitting"
      decision.decision.edits = { other: "Retained" }
      const summary = vi.fn<NonNullable<typeof variant.approval.renderSummary>>(() => null)
      const card = approval(context, {
        ...variant,
        approval: { ...variant.approval, renderFields: false, renderSummary: summary },
      })
      expect(card.fields).toEqual([])
      expect(card.fallbackFields).toEqual([])
      const call = summary.mock.calls[0]
      expect(call?.[3]).toBe(state !== "enabled")
      call?.[2]("name", "Edited")
      if (state === "enabled") {
        expect(decision.onDecisionChange).toHaveBeenCalledWith({
          decision: "pending",
          edits: { other: "Retained", name: "Edited" },
          message: "",
        })
      } else {
        expect(decision.onDecisionChange).not.toHaveBeenCalled()
      }
    }
  )

  it.each([
    ["running", "Changing Original"],
    ["awaiting_approval", "Waiting for project approval"],
    ["failed", "No change confirmed"],
    ["unknown", "No change confirmed"],
  ] as const)("renders configured %s state", (status, copy) => {
    const html = render(props(status))
    expect(html).toContain("Example: Change project")
    expect(html).toContain(copy)
    expect(html).not.toContain("Outcome:")
  })

  it("keeps declines, reasons, provider fallback identity, and details distinct from failures", () => {
    const context = props("denied")
    context.activity.decisionReason = "Check the scope first"
    const html = render(context)
    expect(html).toContain("Change declined. Nothing changed.")
    expect(html).toContain("Check the scope first")
    expect(html).toContain("Project Selected project")
    expect(html).toContain("Requested")
    expect(html).not.toContain(">Failed<")
  })

  it("handles absent, empty, and malformed result envelopes without inferring outcomes", () => {
    const context = props()
    expect(render(context)).toContain("Missing project results")
    context.activity.result = { results: [] }
    expect(render(context)).toContain("No projects")
    context.activity.result = { results: [entry(42)] }
    expect(render(context)).toContain("Invalid project evidence")
    expect(render(context)).not.toContain("Outcome:")
  })

  it.each([false, true])(
    "renders unverified evidence only through the explicit callback (%s)",
    (enabled) => {
      const callback = vi.fn((result: string): ReactNode =>
        createElement("span", null, "Unverified evidence: ", result)
      )
      const config = { ...variant, ...(enabled ? { renderUnverifiedOutcome: callback } : {}) }
      const context = props()
      context.activity.result = {
        results: [
          entry("Evidence", {
            status: "error",
            error_code: "unverified_mutation",
            error_message: "Raw provider message",
          }),
        ],
      }
      const html = render(context, config)
      expect(html).toContain("Check the project before retrying")
      expect(html).not.toContain("Raw provider message")
      expect(html).not.toContain("Outcome: Evidence")
      expect(callback).toHaveBeenCalledTimes(enabled ? 1 : 0)
      if (enabled) expect(html).toContain("Unverified evidence: Evidence")
      else expect(html).not.toContain("Evidence")
    }
  )

  it("does not render unverified evidence from malformed data or known failures", () => {
    const context = props()
    const callback = vi.fn(() => "Unexpected evidence")
    context.activity.result = {
      results: [
        entry(42, { status: "error", error_code: "unverified_mutation" }),
        entry("Known failure data", { status: "error", error_code: "rejected" }),
      ],
    }
    const html = render(context, { ...variant, renderUnverifiedOutcome: callback })
    expect(callback).not.toHaveBeenCalled()
    expect(html).toContain("Check the project before retrying")
    expect(html).not.toContain("Known failure data")
  })

  it("retains result indexes across failed, malformed, successful, and unverified siblings", () => {
    const context = props()
    context.activity.result = {
      results: [
        entry("Ignored", { status: "error", error_message: "Unavailable" }),
        entry(42),
        entry("Third"),
        entry("Fourth", { status: "error", error_code: "unverified_mutation" }),
        entry("Fifth"),
      ],
    }
    const html = render(context, {
      ...variant,
      renderUnverifiedOutcome: (value) => createElement("span", null, "Evidence: ", value),
    })
    expect(html).toContain("2/5 connections")
    expect(html).toContain("Unavailable")
    expect(html).toContain("Invalid project evidence")
    expect(html).toContain("Outcome: Third")
    expect(html).toContain("Evidence: Fourth")
    expect(html).toContain("Outcome: Fifth")
    expect(html).not.toContain("Ignored")
    expect(html).toContain("Project code")
    expect(html).toContain("Project 123")
  })

  it("uses custom failure rendering for fallback and settled errors", () => {
    const config = {
      ...variant,
      renderFailure: (args: Args | null, description: string) =>
        createElement("span", null, "Target ", args?.name, ": ", description),
    }
    expect(render(props("failed"), config)).toContain("Target Original: No change confirmed")
    const context = props()
    context.activity.result = {
      results: [entry(null, { status: "error", error_message: "Unavailable" })],
    }
    expect(render(context, config)).toContain("Target Original: Unavailable")
  })

  it("retains presenter keys, own-name matching, and approval routing", () => {
    const presenter = createIntegrationWritePresenter({
      key: "example-change",
      variants: { change_project: defineIntegrationWriteVariant(provider, variant) },
    })
    expect(presenter.key).toBe("example-change")
    expect(presenter.handlesApprovals).toBe(true)
    expect(presenter.matches(props().activity)).toBe(true)
    const context = props()
    context.activity.name = "toString"
    expect(presenter.matches(context.activity)).toBe(false)
    context.activity.name = "unsupported"
    expect(presenter.render(context)).toBeNull()
  })
})
