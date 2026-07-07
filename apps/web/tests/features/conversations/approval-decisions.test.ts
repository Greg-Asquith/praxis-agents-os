import { describe, expect, it } from "vitest"

import {
  DEFAULT_APPROVAL_DECISION,
  approveDecision,
  buildResumeDecisions,
  denyDecision,
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
  it("approves decisions while preserving only existing override args", () => {
    expect(approveDecision(DEFAULT_APPROVAL_DECISION)).toEqual({
      decision: "approved",
      message: "",
      overrideArgs: "",
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
