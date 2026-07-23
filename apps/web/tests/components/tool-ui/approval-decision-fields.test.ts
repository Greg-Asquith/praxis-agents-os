import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ApprovalRequestFields, type ApprovalField } from "@/components/tool-ui/approval-card"

describe("ApprovalRequestFields", () => {
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

    expect(html).toContain("Openai")
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
})

function approvalField(key: string, label: string, format: ApprovalField["format"]): ApprovalField {
  return {
    key,
    label,
    format,
    editable: false,
    placeholder: "",
    options: [],
    secondary: false,
  }
}
