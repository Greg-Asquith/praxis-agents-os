import { describe, expect, it } from "vitest"

import {
  DEFAULT_APPROVAL_DECISION,
  approveDecision,
  buildResumeDecisions,
  denyDecision,
  shouldAutoSubmitDecisions,
  summarizeApprovalDecisions,
  type LocalApprovalDecisionMap,
} from "@/features/conversations/approval-decisions"
import type { PendingToolApproval } from "@/features/conversations/types"

const approvals: PendingToolApproval[] = [
  {
    tool_call_id: "tool-1",
    name: "read_file",
    args: { file_id: "file-1" },
  },
  {
    tool_call_id: "tool-2",
    name: "send_email",
    args: { to: "user@example.com" },
  },
  {
    tool_call_id: "tool-3",
    name: "write_file",
    args: { name: "draft.md" },
  },
]

describe("approval decision helpers", () => {
  it("approves decisions while preserving pending or approved override args", () => {
    expect(approveDecision(DEFAULT_APPROVAL_DECISION)).toEqual({
      decision: "approved",
      message: "",
      overrideArgs: "",
    })
    expect(
      approveDecision({ decision: "pending", message: "", overrideArgs: '{"ok":true}' })
    ).toEqual({
      decision: "approved",
      message: "",
      overrideArgs: '{"ok":true}',
    })
    expect(
      approveDecision({ decision: "approved", message: "", overrideArgs: '{"ok":true}' })
    ).toEqual({
      decision: "approved",
      message: "",
      overrideArgs: '{"ok":true}',
    })
    expect(approveDecision({ decision: "denied", message: "No", overrideArgs: "" })).toEqual({
      decision: "approved",
      message: "",
      overrideArgs: "",
    })
  })

  it("denies decisions while preserving only existing denial messages", () => {
    expect(denyDecision(DEFAULT_APPROVAL_DECISION)).toEqual({
      decision: "denied",
      message: "",
      overrideArgs: "",
    })
    expect(denyDecision({ decision: "denied", message: "Needs review", overrideArgs: "" })).toEqual(
      {
        decision: "denied",
        message: "Needs review",
        overrideArgs: "",
      }
    )
    expect(
      denyDecision({ decision: "approved", message: "", overrideArgs: '{"ok":true}' })
    ).toEqual({
      decision: "denied",
      message: "",
      overrideArgs: "",
    })
  })

  it("summarizes pending, approved, and denied decisions", () => {
    const decisions: LocalApprovalDecisionMap = {
      "tool-1": { decision: "approved", message: "", overrideArgs: "" },
      "tool-2": { decision: "denied", message: "No", overrideArgs: "" },
    }

    expect(summarizeApprovalDecisions(approvals, decisions)).toEqual({
      allDecided: false,
      approved: 1,
      denied: 1,
      pending: 1,
    })
    expect(summarizeApprovalDecisions(approvals.slice(0, 2), decisions)).toEqual({
      allDecided: true,
      approved: 1,
      denied: 1,
      pending: 0,
    })
  })

  it("auto-submits only when a new approval completes an all-approved set", () => {
    const pending = DEFAULT_APPROVAL_DECISION
    const approved = { decision: "approved", message: "", overrideArgs: "" } as const
    const allApproved = { allDecided: true, approved: 2, denied: 0, pending: 0 }

    expect(shouldAutoSubmitDecisions(pending, approved, allApproved)).toBe(true)
    // Editing override args on an already approved decision must not re-submit.
    expect(shouldAutoSubmitDecisions(approved, approved, allApproved)).toBe(false)
    // A denial in the set requires the explicit send action.
    expect(
      shouldAutoSubmitDecisions(pending, approved, {
        allDecided: true,
        approved: 1,
        denied: 1,
        pending: 0,
      })
    ).toBe(false)
    // Undecided requests remain.
    expect(
      shouldAutoSubmitDecisions(pending, approved, {
        allDecided: false,
        approved: 1,
        denied: 0,
        pending: 1,
      })
    ).toBe(false)
    // Denying never auto-submits.
    expect(
      shouldAutoSubmitDecisions(
        pending,
        { decision: "denied", message: "", overrideArgs: "" },
        {
          allDecided: true,
          approved: 0,
          denied: 1,
          pending: 0,
        }
      )
    ).toBe(false)
  })

  it("builds resume payloads and validates pending or invalid overrides", () => {
    expect(buildResumeDecisions(approvals, {})).toBe(
      "Choose approve or deny for every tool request."
    )
    expect(
      buildResumeDecisions(approvals.slice(0, 1), {
        "tool-1": { decision: "approved", message: "", overrideArgs: "[]" },
      })
    ).toBe("Override args must be a JSON object.")
    expect(
      buildResumeDecisions(approvals.slice(0, 2), {
        "tool-1": { decision: "approved", message: "", overrideArgs: '{"limit":10}' },
        "tool-2": { decision: "denied", message: "  Too risky.  ", overrideArgs: "" },
      })
    ).toEqual([
      {
        decision: "approved",
        override_args: { limit: 10 },
        tool_call_id: "tool-1",
      },
      {
        decision: "denied",
        message: "Too risky.",
        tool_call_id: "tool-2",
      },
    ])
  })
})
