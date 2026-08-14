import { describe, expect, it } from "vitest"

import type { ApprovalField } from "@/components/tool-ui/approval-card"
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

  it("replaces record rows exactly while preserving typed cell values", () => {
    const approval: PendingToolApproval = {
      tool_call_id: "records-1",
      name: "records_write",
      args: {
        rows: [
          { text: "old", match_type: "EXACT", score: 1 },
          { text: "remove me", match_type: "PHRASE", score: 2 },
        ],
        mode: "apply",
      },
    }
    const editedRows = [
      { text: "new", match_type: "PHRASE", score: 1.5 },
      { text: "added", match_type: "EXACT", score: 3 },
    ]

    expect(
      buildResumeDecisions([approval], {
        "records-1": {
          decision: "approved",
          message: "",
          edits: { rows: editedRows },
        },
      })
    ).toEqual([
      {
        decision: "approved",
        override_args: { rows: editedRows, mode: "apply" },
        tool_call_id: "records-1",
      },
    ])
  })

  it("sends no override for untouched record rows", () => {
    const rows = [{ text: "jobs", match_type: "EXACT" }]
    const approval: PendingToolApproval = {
      tool_call_id: "records-1",
      name: "records_write",
      args: { rows },
    }

    expect(
      buildResumeDecisions([approval], {
        "records-1": {
          decision: "approved",
          message: "",
          edits: { rows: rows.map((row) => ({ ...row })) },
        },
      })
    ).toEqual([{ decision: "approved", override_args: null, tool_call_id: "records-1" }])
  })

  it("rejects incomplete record edits using the declared presentation", () => {
    const approval: PendingToolApproval = {
      tool_call_id: "records-1",
      name: "records_write",
      args: { rows: [{ text: "jobs", match_type: "EXACT" }] },
    }
    const fields: ApprovalField[] = [
      {
        key: "rows",
        label: "Negative Keywords",
        format: "records",
        editable: true,
        min_rows: 1,
        options: [],
        placeholder: "",
        secondary: false,
        columns: [
          { key: "text", label: "Keyword", options: [], placeholder: "", required: true },
          {
            key: "match_type",
            label: "Match Type",
            options: ["EXACT", "PHRASE"],
            placeholder: "",
            required: true,
          },
        ],
      },
    ]
    const fieldsForTool = () => fields

    for (const rows of [[], [{ text: "  ", match_type: "EXACT" }]]) {
      expect(
        buildResumeDecisions(
          [approval],
          {
            "records-1": {
              decision: "approved",
              message: "",
              edits: { rows },
            },
          },
          fieldsForTool
        )
      ).toBe("This request can no longer be edited. Refresh and try again.")
    }
  })

  it("does not classify an empty array as records or entity references without metadata", () => {
    const approval: PendingToolApproval = {
      tool_call_id: "records-1",
      name: "records_write",
      args: { rows: [{ text: "jobs", match_type: "EXACT" }] },
    }

    expect(
      buildResumeDecisions([approval], {
        "records-1": { decision: "approved", message: "", edits: { rows: [] } },
      })
    ).toBe("This request can no longer be edited. Refresh and try again.")
  })

  it("submits exact structured entity references selected by the operator", () => {
    const original = {
      version: 1 as const,
      entity_kind: "file",
      entity_id: "file-1",
      label: "Draft plan.md",
    }
    const selected = { ...original, entity_id: "file-2", label: "Final plan.md" }
    const approval: PendingToolApproval = {
      tool_call_id: "file-1",
      name: "read_file",
      args: { file_id: original, mode: "content" },
    }

    expect(
      buildResumeDecisions([approval], {
        "file-1": {
          decision: "approved",
          message: "",
          edits: { file_id: selected },
        },
      })
    ).toEqual([
      {
        decision: "approved",
        override_args: { file_id: selected, mode: "content" },
        tool_call_id: "file-1",
      },
    ])
  })

  it("submits scoped multi-entity references without flattening their account scope", () => {
    const first = {
      version: 1 as const,
      entity_kind: "google_ads_campaign",
      customer_id: "1234567890",
      campaign_id: "111",
      label: "Spring campaign",
    }
    const second = {
      ...first,
      customer_id: "2222222222",
      campaign_id: "222",
      label: "Summer campaign",
    }
    const approval: PendingToolApproval = {
      tool_call_id: "campaigns-1",
      name: "google_ads_update_campaign_status",
      args: { campaign_ids: [first], status: "PAUSED" },
    }

    expect(
      buildResumeDecisions([approval], {
        "campaigns-1": {
          decision: "approved",
          message: "",
          edits: { campaign_ids: [first, second] },
        },
      })
    ).toEqual([
      {
        decision: "approved",
        override_args: { campaign_ids: [first, second], status: "PAUSED" },
        tool_call_id: "campaigns-1",
      },
    ])
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
