import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import {
  ApprovalRequestFields,
  ToolApprovalDecisionCard,
  type ApprovalField,
} from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { resolveToolField } from "@/components/tool-ui/field-resolution"
import { nextKeyValueFieldName } from "@/components/tool-ui/keyvalue-field-values"
import {
  addRecordRow,
  configuredRecordCellCount,
  keyedRecordRows,
  normalizeRecordNumericInput,
  recordRowsValidity,
  removeRecordRow,
  toggleRecordRowExpansion,
  updateRecordCell,
} from "@/components/tool-ui/records-field-values"

describe("ApprovalRequestFields", () => {
  it("uses two columns for compact fields and full width for long-form fields", () => {
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "memory-1",
        args: {
          kind: "core",
          scope: "user",
          title: "Python preference",
          content: "Prefers Python.",
          importance: 4,
        },
        decision: { decision: "pending", edits: {}, message: "" },
        disabled: false,
        fallbackFields: [],
        fields: [
          {
            ...approvalField("kind", "Kind", "text"),
            editable: true,
            options: ["core", "note"],
          },
          {
            ...approvalField("scope", "Scope", "text"),
            editable: true,
            options: ["agent", "user", "workspace"],
          },
          { ...approvalField("title", "Memory", "text"), editable: true },
          { ...approvalField("content", "Details", "markdown"), editable: true },
          { ...approvalField("importance", "Importance", "number"), editable: true },
        ],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain("sm:grid-cols-2")
    expect(html).toContain("sm:col-span-2")
    expect(html).toContain('value="core"')
    expect(html).toContain('value="user"')
  })

  it("title-cases option labels while preserving their submitted values", () => {
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "search-1",
        args: { model_provider: "openai" },
        decision: { decision: "pending", edits: {}, message: "" },
        disabled: false,
        fallbackFields: [],
        fields: [
          {
            key: "model_provider",
            label: "Search Provider",
            min_rows: 0,
            format: "text",
            editable: true,
            placeholder: "",
            options: ["anthropic", "google", "openai"],
            secondary: false,
          },
        ],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain("OpenAI")
    expect(html).toContain('value="openai"')
    expect(html).not.toContain(">openai<")
  })

  it("uses shared field resolution and rendering for non-editable approval arguments", () => {
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "export-1",
        args: {
          attempts: 3,
          created_at: "2026-07-07T10:00:00.000Z",
          size: 2048,
          source: "https://praxis-agents.ai/docs/tools",
          tags: [
            "report",
            {
              node: "praxis_untrusted",
              source_kind: "gmail_message",
              source_ref: "message-1",
              content: "external",
            },
          ],
          title: {
            node: "praxis_untrusted",
            source_kind: "gmail_message",
            source_ref: "message-1",
            content: "Quarterly update",
          },
        },
        decision: { decision: "pending", edits: {}, message: "" },
        disabled: false,
        fallbackFields: [],
        fields: [
          approvalField("attempts", "Attempts", "text"),
          approvalField("created_at", "Created", "datetime"),
          approvalField("size", "Size", "bytes"),
          approvalField("source", "Source", "url"),
          approvalField("tags", "Tags", "list"),
          approvalField("title", "Title", "text"),
        ],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain(">3<")
    expect(html).toContain("2.0 KB")
    expect(html).toContain("2026")
    expect(html).not.toContain("2026-07-07T10:00:00.000Z")
    expect(html).toContain('href="https://praxis-agents.ai/docs/tools"')
    expect(html).toContain("praxis-agents.ai/docs/tools")
    expect(html).toContain("report")
    expect(html).toContain("external")
    expect(html).toContain("Quarterly update")
  })

  it("resolves decided fields through the same pipeline after applying edits", () => {
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "export-2",
        args: { attempts: 3, source: "https://example.com/original" },
        decision: {
          decision: "approved",
          edits: { source: "https://praxis-agents.ai/approved" },
          message: "",
        },
        disabled: true,
        fallbackFields: [],
        fields: [
          approvalField("attempts", "Attempts", "text"),
          { ...approvalField("source", "Source", "url"), editable: true },
        ],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain(">3<")
    expect(html).toContain('href="https://praxis-agents.ai/approved"')
    expect(html).not.toContain("example.com/original")
  })

  it("renders typed editors for numbers, string lists, and flat key/value fields", () => {
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "typed-1",
        args: {
          importance: 3,
          recipients: ["one@example.com", "two@example.com"],
          fields: {
            Name: "Praxis",
            Active: true,
            Score: 4,
            Linked: [{ id: "record-1" }],
          },
        },
        decision: { decision: "pending", edits: {}, message: "" },
        disabled: false,
        fallbackFields: [],
        fields: [
          { ...approvalField("importance", "Importance", "number"), editable: true },
          { ...approvalField("recipients", "Recipients", "list"), editable: true },
          { ...approvalField("fields", "Fields", "keyvalue"), editable: true },
        ],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain('type="number"')
    expect(html).toContain('inputMode="decimal"')
    expect(html).toContain("one@example.com")
    expect(html).toContain("Remove one@example.com")
    expect(html).toContain("Add list item")
    expect(html).toContain("Add Field")
    expect(html).toContain("Active")
    expect(html).toContain("Complex value — read only")
    expect(html).not.toContain("record-1")
  })

  it("re-resolves typed edits through read-only fields after approval", () => {
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "typed-2",
        args: {
          importance: 3,
          recipients: ["one@example.com"],
          fields: { Name: "Praxis", Active: true },
        },
        decision: {
          decision: "approved",
          edits: {
            importance: 5,
            recipients: ["two@example.com", "three@example.com"],
            fields: { Name: "Praxis Agents", Active: false },
          },
          message: "",
        },
        disabled: true,
        fallbackFields: [],
        fields: [
          { ...approvalField("importance", "Importance", "number"), editable: true },
          { ...approvalField("recipients", "Recipients", "list"), editable: true },
          { ...approvalField("fields", "Fields", "keyvalue"), editable: true },
        ],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain(">5<")
    expect(html).toContain("two@example.com")
    expect(html).toContain("three@example.com")
    expect(html).toContain("Praxis Agents")
    expect(html).toContain("No")
    expect(html).not.toContain('type="number"')
    expect(html).not.toContain("one@example.com")
  })

  it("renders declared record rows with select columns and every proposed row", () => {
    const rows = [
      { text: "free shipping", match_type: "PHRASE", score: 1.5 },
      { text: "jobs", match_type: "EXACT", score: 2 },
    ]
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "records-1",
        args: { rows },
        decision: { decision: "pending", edits: {}, message: "" },
        disabled: false,
        fallbackFields: [],
        fields: [
          {
            ...approvalField("rows", "Negative Keywords", "records"),
            editable: true,
            min_rows: 1,
            columns: [
              {
                key: "text",
                label: "Keyword",
                options: [],
                placeholder: "Enter keyword",
                required: true,
              },
              {
                key: "match_type",
                label: "Match Type",
                options: ["EXACT", "PHRASE"],
                placeholder: "",
                required: true,
              },
              { key: "score", label: "Score", options: [], placeholder: "", required: false },
            ],
          },
        ],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain("2 rows")
    expect(html).toContain("Add Row")
    expect(html).toContain("free shipping")
    expect(html).toContain("jobs")
    expect(html).toContain('role="combobox"')
    expect(html).toContain(">PHRASE<")
    expect(html).toContain(">EXACT<")
    expect(html).toContain('type="number"')
    expect(html).toContain('value="1.5"')
    expect(html).toContain('value="2"')
    expect(html).toContain('aria-label="Remove row 1"')
    expect(html).toContain('aria-label="Remove row 2"')
    expect(html).toContain('aria-label="Keyword, row 1"')
    expect(html).toContain('aria-label="Match Type, row 2"')
    expect(html.match(/scope="col"/g)).toHaveLength(4)
    expect(html).toContain('id="records-1-rows-edit-label"')
    expect(html).toContain('aria-labelledby="records-1-rows-edit-label"')
  })

  it("shows record completeness errors and disables approval", () => {
    const field: ApprovalField = {
      ...approvalField("rows", "Negative Keywords", "records"),
      editable: true,
      min_rows: 1,
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
    }
    const html = renderToStaticMarkup(
      createElement(ToolApprovalDecisionCard, {
        activityId: "records-invalid",
        args: { rows: [{ text: "", match_type: "EXACT" }] },
        controls: {
          decision: { decision: "pending", edits: {}, message: "" },
          disabled: false,
          error: null,
          onDecisionChange: () => undefined,
          onRetry: () => undefined,
          pendingCount: 1,
          submitting: false,
        },
        fields: [field],
        label: "Add Negative Keywords",
        toolName: "google_ads_add_negative_keywords",
      })
    )

    expect(html).toContain("Keyword is required in row 1.")
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve<\/button>/)
    expect(html).toContain('aria-live="polite"')
  })

  it("allows approval when a secondary records field is omitted", () => {
    const field: ApprovalField = {
      ...approvalField("properties", "Properties", "records"),
      editable: true,
      secondary: true,
      columns: [
        { key: "name", label: "Property", options: [], placeholder: "", required: true },
        { key: "value", label: "Value", options: [], placeholder: "", required: false },
      ],
    }
    const html = renderToStaticMarkup(
      createElement(ToolApprovalDecisionCard, {
        activityId: "optional-records",
        args: { title: "Launch notes" },
        controls: {
          decision: { decision: "pending", edits: {}, message: "" },
          disabled: false,
          error: null,
          onDecisionChange: () => undefined,
          onRetry: () => undefined,
          pendingCount: 1,
          submitting: false,
        },
        fields: [field],
        label: "Create Notion Page",
        toolName: "notion_create_page",
      })
    )

    expect(html).toMatch(/<button[^>]*>Approve<\/button>/)
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve<\/button>/)
  })

  it("blocks approval but permits decline when display enrichment fails", () => {
    const html = renderToStaticMarkup(
      createElement(ToolApprovalDecisionCard, {
        activityId: "display-error",
        args: {
          _approval_display_error:
            "Approval details are unavailable. Ask the agent to prepare this action again.",
          amount: "12.50",
        },
        controls: {
          decision: { decision: "pending", edits: {}, message: "" },
          disabled: false,
          error: null,
          onDecisionChange: () => undefined,
          onRetry: () => undefined,
          pendingCount: 1,
          submitting: false,
        },
        label: "Update Campaign Budget",
        toolName: "google_ads_update_campaign_budget_amounts",
      })
    )

    expect(html).toContain("Decline this request")
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve<\/button>/)
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Decline<\/button>/)
  })

  it("adds, removes, and edits record rows without coercing numeric cells", () => {
    const columns = [
      { key: "text", label: "Keyword", options: [], placeholder: "", required: true },
      { key: "score", label: "Score", options: [], placeholder: "", required: false },
    ]
    const original = [{ text: "jobs", score: 2 }]

    const added = addRecordRow(original, columns)
    expect(added).toEqual([{ text: "jobs", score: 2 }, { text: "" }])
    expect(updateRecordCell(added, 0, "score", 3.5)).toEqual([
      { text: "jobs", score: 3.5 },
      { text: "" },
    ])
    expect(removeRecordRow(added, 0)).toEqual([{ text: "" }])
    expect(original).toEqual([{ text: "jobs", score: 2 }])
  })

  it("accepts only finite numeric record edits", () => {
    expect(normalizeRecordNumericInput("0")).toBe(0)
    expect(normalizeRecordNumericInput("-2.5")).toBe(-2.5)
    expect(normalizeRecordNumericInput("3.25")).toBe(3.25)

    for (const value of ["", "   ", "not-a-number", "NaN", "Infinity", "-Infinity"]) {
      expect(normalizeRecordNumericInput(value)).toBeNull()
    }
  })

  it("validates minimum rows, required cells, options, and optional numeric values", () => {
    const columns = [
      { key: "text", label: "Keyword", options: [], placeholder: "", required: true },
      {
        key: "match_type",
        label: "Match Type",
        options: ["EXACT", "PHRASE"],
        placeholder: "",
        required: true,
      },
      { key: "score", label: "Score", options: [], placeholder: "", required: false },
    ]

    expect(recordRowsValidity([], columns, 1)).toEqual({
      isRecords: true,
      error: "Add at least 1 row before approving.",
    })
    expect(recordRowsValidity([{ text: "  ", match_type: "EXACT", score: 0 }], columns, 1)).toEqual(
      { isRecords: true, error: "Keyword is required in row 1." }
    )
    expect(
      recordRowsValidity([{ text: "jobs", match_type: "BROAD", score: -2.5 }], columns, 1)
    ).toEqual({ isRecords: true, error: "Choose a valid match type in row 1." })
    expect(
      recordRowsValidity([{ text: "jobs", match_type: "EXACT", score: -2.5 }], columns, 1)
    ).toEqual({ isRecords: true, error: null })
  })

  it("keeps record row keys stable while cell values change", () => {
    const keys = ["row-1", "row-2"]
    const original = [
      { text: "jobs", score: 2 },
      { text: "careers", score: 3 },
    ]
    const updated = updateRecordCell(original, 0, "text", "new jobs")

    expect(keyedRecordRows(original, keys).map((row) => row.key)).toEqual(keys)
    expect(keyedRecordRows(updated, keys).map((row) => row.key)).toEqual(keys)
  })

  it("preserves typed list and key-value cells in secondary record columns", () => {
    const columns = [
      {
        key: "text",
        label: "Keyword",
        options: [],
        placeholder: "",
        required: true,
        format: "text" as const,
        secondary: false,
      },
      {
        key: "final_urls",
        label: "Final URLs",
        options: [],
        placeholder: "",
        required: false,
        format: "list" as const,
        secondary: true,
      },
      {
        key: "url_custom_parameters",
        label: "URL Custom Parameters",
        options: [],
        placeholder: "",
        required: false,
        format: "keyvalue" as const,
        secondary: true,
      },
    ]
    const row = {
      text: "trail shoes",
      final_urls: ["https://example.com/trail"],
      url_custom_parameters: { audience: "trail" },
    }

    expect(recordRowsValidity([row], columns, 1)).toEqual({ isRecords: true, error: null })
    expect(addRecordRow([], columns)).toEqual([
      { text: "", final_urls: [], url_custom_parameters: {} },
    ])
    expect(
      configuredRecordCellCount(
        row,
        columns.filter((column) => column.secondary)
      )
    ).toBe(2)
  })

  it("renders omitted optional record cells without accepting malformed rows", () => {
    const columns = [
      { key: "text", label: "Keyword", options: [], placeholder: "", required: true },
      { key: "status", label: "Status", options: ["ENABLED"], placeholder: "", required: false },
      {
        key: "final_urls",
        label: "Final URLs",
        options: [],
        placeholder: "",
        required: false,
        format: "list" as const,
      },
      {
        key: "parameters",
        label: "Parameters",
        options: [],
        placeholder: "",
        required: false,
        format: "keyvalue" as const,
      },
    ]
    const field = { columns, format: "records" as const, key: "keywords", label: "Keywords" }
    const compact = resolveToolField(field, [{ text: "shoes" }])
    const projected = resolveToolField(field, [
      { text: "shoes", status: "", final_urls: [], parameters: {} },
    ])

    expect(compact?.records?.[0]?.cells.map((cell) => cell.value)).toEqual(["shoes", "—", "—", "—"])
    expect(projected?.records?.[0]?.cells.map((cell) => cell.value)).toEqual([
      "shoes",
      "—",
      "—",
      "—",
    ])
    expect(resolveToolField(field, [{ status: "ENABLED" }])).toBeNull()
    expect(resolveToolField(field, [{ text: "shoes", unknown: "x" }])).toBeNull()
    expect(resolveToolField(field, [{ text: "shoes", final_urls: [1] }])).toBeNull()
    expect(resolveToolField(field, [{ text: "shoes", parameters: { nested: {} } }])).toBeNull()
  })

  it("applies declared row defaults and key-value entry limits", () => {
    const columns = [
      { key: "text", label: "Keyword", options: [], placeholder: "", required: true },
      {
        default_value: "ENABLED",
        key: "status",
        label: "Status",
        options: ["ENABLED", "PAUSED"],
        placeholder: "",
        required: false,
      },
      {
        format: "keyvalue" as const,
        key: "parameters",
        label: "Parameters",
        max_entries: 1,
        options: [],
        placeholder: "",
        required: false,
      },
    ]
    expect(addRecordRow([], columns)).toEqual([{ parameters: {}, status: "ENABLED", text: "" }])
    expect(
      recordRowsValidity([{ text: "shoes", parameters: { one: "1", two: "2" } }], columns, 1)
    ).toEqual({
      error: "Parameters can contain at most 1 entries in row 1.",
      isRecords: true,
    })
    expect(nextKeyValueFieldName({ constructor: "x" }, [])).toBe("field2")
    expect(nextKeyValueFieldName({ field2: "x" }, ["field1"])).toBe("field3")
  })

  it("discloses configured secondary fields and toggles row expansion", () => {
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "advanced-records",
        args: {
          rows: [
            {
              text: "trail shoes",
              final_urls: ["https://example.com/trail"],
              cpc_bid: "2.50",
            },
          ],
        },
        decision: { decision: "pending", edits: {}, message: "" },
        disabled: false,
        fallbackFields: [],
        fields: [
          {
            ...approvalField("rows", "Keywords", "records"),
            editable: true,
            columns: [
              { key: "text", label: "Keyword", options: [], placeholder: "", required: true },
              {
                key: "cpc_bid",
                label: "CPC Bid",
                options: [],
                placeholder: "",
                required: false,
                secondary: true,
              },
              {
                key: "final_urls",
                label: "Final URLs",
                options: [],
                placeholder: "",
                required: false,
                format: "list",
                secondary: true,
              },
            ],
          },
        ],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain("2 configured")
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain("Show more fields in row 1. 2 configured.")
    const expanded = toggleRecordRowExpansion(new Set<string>(), "row-1")
    expect(expanded.has("row-1")).toBe(true)
    expect(toggleRecordRowExpansion(expanded, "row-1").has("row-1")).toBe(false)
  })

  it("renders locked record rows through the read-only table", () => {
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "records-2",
        args: { rows: [{ text: "jobs", match_type: "EXACT" }] },
        decision: { decision: "approved", edits: {}, message: "" },
        disabled: true,
        fallbackFields: [],
        fields: [
          {
            ...approvalField("rows", "Negative Keywords", "records"),
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
        ],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain("1 row")
    expect(html).toContain("Keyword")
    expect(html).toContain("jobs")
    expect(html).toContain("EXACT")
    expect(html).not.toContain("Add Row")
    expect(html).not.toContain("<input")
  })

  it("edits markdown strings as plain text", () => {
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "markdown-1",
        args: { content: "**Keep this Markdown**" },
        decision: { decision: "pending", edits: {}, message: "" },
        disabled: false,
        fallbackFields: [],
        fields: [{ ...approvalField("content", "Details", "markdown"), editable: true }],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain("<textarea")
    expect(html).toContain("**Keep this Markdown**")
  })

  it("fails closed when an entity field has no conversation context", () => {
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "file-1",
        args: {
          file_id: {
            version: 1,
            entity_kind: "file",
            entity_id: "opaque-file-id",
            label: "Model supplied label",
          },
        },
        decision: { decision: "pending", edits: {}, message: "" },
        disabled: false,
        fallbackFields: [],
        fields: [{ ...approvalField("file_id", "File", "entity"), editable: true }],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain("Target unavailable")
    expect(html).toContain("cannot be verified outside its conversation")
    expect(html).not.toContain("opaque-file-id")
    expect(html).not.toContain("Model supplied label")
    expect(html).not.toContain("<input")
  })

  it("shows undeclared executable arguments in a collapsed disclosure", () => {
    const args = {
      title: "Launch guidance",
      content: "Prefer concise release notes.",
      kind: "core",
      scope: "workspace",
      importance: 5,
      metadata: { source: "agent" },
    }
    const fields = [approvalField("title", "Memory", "text")]
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "memory-1",
        args,
        decision: { decision: "pending", edits: {}, message: "" },
        disabled: false,
        fallbackFields: approvalFallbackFields(args, fields),
        fields,
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain("Other Options")
    expect(html).toContain("Kind")
    expect(html).toContain(">core<")
    expect(html).toContain("Scope")
    expect(html).toContain(">workspace<")
    expect(html).toContain("Importance")
    expect(html).toContain(">5<")
    expect(html).toContain("&quot;source&quot;: &quot;agent&quot;")
  })
})

function approvalField(key: string, label: string, format: ApprovalField["format"]): ApprovalField {
  return {
    key,
    label,
    min_rows: 0,
    format,
    editable: false,
    placeholder: "",
    options: [],
    secondary: false,
  }
}
