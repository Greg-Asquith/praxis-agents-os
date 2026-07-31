import { describe, expect, it } from "vitest"

import {
  DEFAULT_APPROVAL_DECISION,
  buildResumeDecisions,
  shouldSubmitDecisions,
  summarizeApprovalDecisions,
  type ApprovalDecisionMap,
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
  it("summarizes pending, approved, and denied decisions", () => {
    const decisions: ApprovalDecisionMap = {
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

  it("merges edited staged writes over replay args instead of the display projection", () => {
    const writeApproval: PendingToolApproval = {
      tool_call_id: "write-1",
      name: "write_file",
      args: {
        name: "draft.md",
        content: "[staged for approval; content omitted]",
        content_bytes: 21,
        content_sha256: "display-hash",
      },
      replay_args: {
        name: "draft.md",
        content_ref: "workspaces/ws/agent-runs/run/staged-tool-inputs/content.txt",
      },
    }

    expect(
      buildResumeDecisions([writeApproval], {
        "write-1": { decision: "approved", message: "", edits: { name: "final.md" } },
      })
    ).toEqual([
      {
        decision: "approved",
        override_args: {
          name: "final.md",
          content_ref: "workspaces/ws/agent-runs/run/staged-tool-inputs/content.txt",
        },
        tool_call_id: "write-1",
      },
    ])
  })

  it("merges typed number, list, and key/value edits structurally", () => {
    const approval: PendingToolApproval = {
      tool_call_id: "typed-1",
      name: "typed_write",
      args: {
        importance: 3,
        recipients: ["one@example.com"],
        fields: {
          Name: "Praxis",
          Score: 3,
          Active: true,
          Linked: [{ id: "record-1" }],
        },
      },
    }

    expect(
      buildResumeDecisions([approval], {
        "typed-1": {
          decision: "approved",
          message: "",
          edits: {
            importance: 5,
            recipients: ["two@example.com", "three@example.com"],
            fields: { Name: "Praxis Agents", Score: 4, Active: false },
          },
        },
      })
    ).toEqual([
      {
        decision: "approved",
        override_args: {
          importance: 5,
          recipients: ["two@example.com", "three@example.com"],
          fields: {
            Name: "Praxis Agents",
            Score: 4,
            Active: false,
            Linked: [{ id: "record-1" }],
          },
        },
        tool_call_id: "typed-1",
      },
    ])
  })

  it("sends Airtable field edits as an object in override args", () => {
    const approval: PendingToolApproval = {
      tool_call_id: "airtable-create-1",
      name: "airtable_create_record",
      args: {
        table: "Projects",
        fields: { Status: "Draft", Owner: "Ada" },
      },
    }

    expect(
      buildResumeDecisions([approval], {
        "airtable-create-1": {
          decision: "approved",
          message: "",
          edits: {
            fields: { Status: "Complete", Owner: "Ada" },
          },
        },
      })
    ).toEqual([
      {
        decision: "approved",
        override_args: {
          table: "Projects",
          fields: { Status: "Complete", Owner: "Ada" },
        },
        tool_call_id: "airtable-create-1",
      },
    ])
  })

  it("drops structurally unchanged typed edits", () => {
    const approval: PendingToolApproval = {
      tool_call_id: "typed-1",
      name: "typed_write",
      args: {
        importance: 3,
        recipients: ["one@example.com", "two@example.com"],
        fields: { Name: "Praxis", Score: 3, Active: true },
      },
    }

    expect(
      buildResumeDecisions([approval], {
        "typed-1": {
          decision: "approved",
          message: "",
          edits: {
            importance: 3,
            recipients: ["one@example.com", "two@example.com"],
            fields: { Name: "Praxis", Score: 3, Active: true },
          },
        },
      })
    ).toEqual([{ decision: "approved", override_args: null, tool_call_id: "typed-1" }])
  })

  it("preserves integer shape and rejects unsupported edited value shapes", () => {
    const integerApproval: PendingToolApproval = {
      tool_call_id: "integer-1",
      name: "save_memory",
      args: { importance: 3 },
    }

    expect(
      buildResumeDecisions([integerApproval], {
        "integer-1": {
          decision: "approved",
          message: "",
          edits: { importance: 4.5 },
        },
      })
    ).toBe("This request can no longer be edited. Refresh and try again.")

    const unsupportedApproval: PendingToolApproval = {
      tool_call_id: "unsupported-1",
      name: "typed_write",
      args: { recipients: [{ address: "one@example.com" }] },
    }
    expect(
      buildResumeDecisions([unsupportedApproval], {
        "unsupported-1": {
          decision: "approved",
          message: "",
          edits: { recipients: ["two@example.com"] },
        },
      })
    ).toBe("This request can no longer be edited. Refresh and try again.")
  })

  it("allows removing scalar rows and cannot overwrite complex read-only rows", () => {
    const approval: PendingToolApproval = {
      tool_call_id: "fields-1",
      name: "airtable_update_record",
      args: {
        fields: {
          Name: "Praxis",
          RemoveMe: "old",
          Linked: [{ id: "record-1" }],
        },
      },
    }

    expect(
      buildResumeDecisions([approval], {
        "fields-1": {
          decision: "approved",
          message: "",
          edits: { fields: { Name: "Praxis", Linked: "clobbered" } },
        },
      })
    ).toEqual([
      {
        decision: "approved",
        override_args: {
          fields: { Name: "Praxis", Linked: [{ id: "record-1" }] },
        },
        tool_call_id: "fields-1",
      },
    ])
  })

  it("drops empty newly added key/value rows", () => {
    const approval: PendingToolApproval = {
      tool_call_id: "fields-1",
      name: "airtable_create_record",
      args: {
        fields: {
          Name: "Praxis",
          ExistingEmpty: "",
        },
      },
    }

    expect(
      buildResumeDecisions([approval], {
        "fields-1": {
          decision: "approved",
          message: "",
          edits: {
            fields: {
              Name: "Praxis Agents",
              ExistingEmpty: "",
              "Field 3": "",
              Notes: "   ",
            },
          },
        },
      })
    ).toEqual([
      {
        decision: "approved",
        override_args: {
          fields: {
            Name: "Praxis Agents",
            ExistingEmpty: "",
          },
        },
        tool_call_id: "fields-1",
      },
    ])
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
