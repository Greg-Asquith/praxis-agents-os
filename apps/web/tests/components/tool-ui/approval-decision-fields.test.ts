import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ApprovalRequestFields, type ApprovalField } from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"

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
    format,
    editable: false,
    placeholder: "",
    options: [],
    secondary: false,
  }
}
