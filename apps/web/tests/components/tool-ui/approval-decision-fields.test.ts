import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

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
  normalizeRecordNumericInput,
  recordRowsValidity,
  removeRecordRow,
  updateRecordCell,
} from "@/components/tool-ui/records-field-values"

import { Select } from "@/components/ui/select"

vi.mock("@/components/ui/select", async (importOriginal) => {
  const original = await importOriginal<{ Select: typeof Select }>()
  return { ...original, Select: vi.fn(original.Select) }
})

describe("ApprovalRequestFields", () => {
  it("replaces an unsupported aspect ratio when the provider changes", () => {
    vi.mocked(Select).mockClear()
    const onEditsChange = vi.fn()
    const fields: ApprovalField[] = [
      {
        ...approvalField("model_provider", "Image Provider", "text"),
        editable: true,
        options: ["google", "openai"],
      },
      {
        ...approvalField("aspect_ratio", "Aspect Ratio", "text"),
        editable: true,
        options: ["1:1", "16:9"],
        options_by_field: "model_provider",
        options_by_value: { google: ["1:1", "16:9"], openai: ["1:1"] },
      },
    ]
    renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "image",
        args: { model_provider: "google", aspect_ratio: "16:9" },
        decision: { decision: "pending", edits: { prompt: "A red panda" }, message: "" },
        disabled: false,
        fallbackFields: [],
        fields,
        onEditsChange,
      })
    )
    vi.mocked(Select).mock.calls[0]?.[0].onValueChange?.("openai", {
      reason: "none",
      event: new Event("change"),
      cancel: () => undefined,
      allowPropagation: () => undefined,
      isCanceled: false,
      isPropagationAllowed: false,
      trigger: undefined,
    })
    expect(onEditsChange).toHaveBeenCalledWith({
      prompt: "A red panda",
      model_provider: "openai",
      aspect_ratio: "1:1",
    })
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
