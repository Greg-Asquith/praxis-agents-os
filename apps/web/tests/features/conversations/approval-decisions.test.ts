import { describe, expect, it } from "vitest"

import {
  DEFAULT_APPROVAL_DECISION,
  approveDecision,
  buildResumeDecisions,
  denyDecision,
  shouldSubmitDecisions,
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
  it("approves decisions while preserving pending or approved edits", () => {
    expect(approveDecision(DEFAULT_APPROVAL_DECISION)).toEqual({
      decision: "approved",
      message: "",
      edits: {},
    })
    expect(
      approveDecision({ decision: "pending", message: "", edits: { query: "UK pricing" } })
    ).toEqual({
      decision: "approved",
      message: "",
      edits: { query: "UK pricing" },
    })
    expect(
      approveDecision({ decision: "approved", message: "", edits: { query: "UK pricing" } })
    ).toEqual({
      decision: "approved",
      message: "",
      edits: { query: "UK pricing" },
    })
    expect(approveDecision({ decision: "denied", message: "No", edits: {} })).toEqual({
      decision: "approved",
      message: "",
      edits: {},
    })
  })

  it("denies decisions while preserving only existing denial messages and clearing edits", () => {
    expect(denyDecision(DEFAULT_APPROVAL_DECISION)).toEqual({
      decision: "denied",
      message: "",
      edits: {},
    })
    expect(denyDecision({ decision: "denied", message: "Needs review", edits: {} })).toEqual({
      decision: "denied",
      message: "Needs review",
      edits: {},
    })
    expect(
      denyDecision({ decision: "approved", message: "", edits: { query: "UK pricing" } })
    ).toEqual({
      decision: "denied",
      message: "",
      edits: {},
    })
  })

  it("summarizes pending, approved, and denied decisions", () => {
    const decisions: LocalApprovalDecisionMap = {
      "tool-1": { decision: "approved", message: "", edits: {} },
      "tool-2": { decision: "denied", message: "No", edits: {} },
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

  it("submits when a new decision completes the set", () => {
    const pending = DEFAULT_APPROVAL_DECISION
    const approved = { decision: "approved", message: "", edits: {} } as const
    const allApproved = { allDecided: true, approved: 2, denied: 0, pending: 0 }

    expect(shouldSubmitDecisions(pending, approved, allApproved)).toBe(true)
    expect(shouldSubmitDecisions(approved, approved, allApproved)).toBe(false)
    expect(
      shouldSubmitDecisions(pending, approved, {
        allDecided: true,
        approved: 1,
        denied: 1,
        pending: 0,
      })
    ).toBe(true)
    expect(
      shouldSubmitDecisions(pending, approved, {
        allDecided: false,
        approved: 1,
        denied: 0,
        pending: 1,
      })
    ).toBe(false)
    expect(
      shouldSubmitDecisions(
        pending,
        { decision: "denied", message: "", edits: {} },
        {
          allDecided: true,
          approved: 0,
          denied: 1,
          pending: 0,
        }
      )
    ).toBe(true)
  })

  it("requires a decision for every request", () => {
    expect(buildResumeDecisions(approvals, {})).toBe(
      "Choose approve or decline for every tool request."
    )
  })

  it("merges trimmed edits into the full original argument object", () => {
    const searchApproval: PendingToolApproval = {
      tool_call_id: "search-1",
      name: "web_search",
      args: { query: "Praxis Agents", model_provider: "openai", metadata: { source: "agent" } },
    }

    expect(
      buildResumeDecisions([searchApproval], {
        "search-1": { decision: "approved", message: "", edits: { query: "  UK pricing  " } },
      })
    ).toEqual([
      {
        decision: "approved",
        override_args: {
          query: "UK pricing",
          model_provider: "openai",
          metadata: { source: "agent" },
        },
        tool_call_id: "search-1",
      },
    ])
  })

  it("sends no override when edits are unchanged or only whitespace", () => {
    const searchApproval: PendingToolApproval = {
      tool_call_id: "search-1",
      name: "web_search",
      args: { query: "Praxis Agents", model_provider: "openai" },
    }

    expect(
      buildResumeDecisions([searchApproval], {
        "search-1": { decision: "approved", message: "", edits: { query: " Praxis Agents " } },
      })
    ).toEqual([{ decision: "approved", override_args: null, tool_call_id: "search-1" }])
    expect(
      buildResumeDecisions([searchApproval], {
        "search-1": { decision: "approved", message: "", edits: { query: "   " } },
      })
    ).toEqual([{ decision: "approved", override_args: null, tool_call_id: "search-1" }])
  })

  it("builds approved and denied decisions together", () => {
    expect(
      buildResumeDecisions(approvals.slice(0, 2), {
        "tool-1": { decision: "approved", message: "", edits: {} },
        "tool-2": { decision: "denied", message: "  Too risky.  ", edits: {} },
      })
    ).toEqual([
      {
        decision: "approved",
        override_args: null,
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
