import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ToolField, ToolFieldGrid } from "@/features/conversations/components/tool-field"
import { resolveToolField } from "@/components/tool-ui/field-resolution"

describe("ToolField", () => {
  it("renders entity labels without exposing their stable identifiers", () => {
    const reference = {
      version: 1 as const,
      entity_kind: "gmail_message",
      mailbox_id: "mailbox-1",
      message_id: "opaque-message-id",
      label: "Invoice from Acme",
      description: "billing@acme.test",
      scope_label: "Finance mailbox",
    }
    const field = resolveToolField(
      { key: "message_id", label: "Message", format: "entity" },
      reference
    )
    expect(field?.value).toBe("Invoice from Acme")
    if (!field) {
      throw new Error("Expected the entity reference to resolve")
    }

    const html = renderToStaticMarkup(createElement(ToolField, { field }))
    expect(html).toContain("Invoice from Acme")
    expect(html).not.toContain("opaque-message-id")
    expect(html).not.toContain("mailbox-1")
  })

  it("renders entity lists as human-readable chips only", () => {
    const field = resolveToolField(
      { key: "campaign_ids", label: "Campaigns", format: "entity_list" },
      [
        {
          version: 1,
          entity_kind: "google_ads_campaign",
          customer_id: "1234567890",
          campaign_id: "111",
          label: "Spring campaign",
        },
        {
          version: 1,
          entity_kind: "google_ads_campaign",
          customer_id: "2222222222",
          campaign_id: "222",
          label: "Summer campaign",
        },
      ]
    )
    if (!field) {
      throw new Error("Expected the entity list to resolve")
    }
    const html = renderToStaticMarkup(createElement(ToolField, { field }))

    expect(html).toContain("Spring campaign")
    expect(html).toContain("Summer campaign")
    expect(html).not.toContain("account-1")
    expect(html).not.toContain(">111<")
  })

  it("renders safe URL fields as external links with compact labels", () => {
    const html = renderToStaticMarkup(
      createElement(ToolField, {
        field: {
          key: "source",
          label: "Source",
          value: "https://praxis-agents.ai/docs/tools?view=all",
          format: "url",
        },
      })
    )

    expect(html).toContain('href="https://praxis-agents.ai/docs/tools?view=all"')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noreferrer"')
    expect(html).toContain("praxis-agents.ai/docs/tools?view=all")
    expect(html).not.toContain(">https://")
  })

  it("renders result URLs as compact outline actions", () => {
    const html = renderToStaticMarkup(
      createElement(ToolField, {
        field: {
          key: "file_url",
          label: "File",
          value: "https://praxis-agents.ai/files/report.pdf",
          format: "url",
        },
        urlAction: true,
      })
    )

    expect(html).toContain("Open File")
    expect(html).toContain('href="https://praxis-agents.ai/files/report.pdf"')
    expect(html).toContain('target="_blank"')
  })

  it("renders resolved list items as wrapping chips", () => {
    const html = renderToStaticMarkup(
      createElement(ToolField, {
        field: {
          key: "files",
          label: "Files",
          value: "brief.md, notes.txt",
          format: "list",
          items: ["brief.md", "notes.txt"],
        },
      })
    )

    expect(html).toContain("sm:col-span-2")
    expect(html).toContain("brief.md")
    expect(html).toContain("notes.txt")
    expect(html).toContain("flex-wrap")
  })

  it("falls back to the resolved text when list items are unavailable", () => {
    const html = renderToStaticMarkup(
      createElement(ToolField, {
        field: {
          key: "files",
          label: "Files",
          value: "brief.md, notes.txt",
          format: "list",
        },
      })
    )

    expect(html).toContain("brief.md, notes.txt")
    expect(html).not.toContain("flex-wrap")
  })

  it("renders Markdown and scroll-caps long block values", () => {
    const markdown = renderToStaticMarkup(
      createElement(ToolField, {
        field: {
          key: "answer",
          label: "Answer",
          value: "A **clear** answer",
          format: "markdown",
        },
      })
    )
    const longText = renderToStaticMarkup(
      createElement(ToolField, {
        field: { key: "result", label: "Result", value: "x".repeat(121), format: "text" },
      })
    )

    expect(markdown).toContain("<strong")
    expect(markdown).toContain("clear")
    expect(markdown).toContain("max-h-80")
    expect(longText).toContain("max-h-80")
    expect(longText).toContain("sm:col-span-2")
  })

  it("renders declared result records as a bounded table", () => {
    const field = resolveToolField(
      {
        key: "results",
        label: "Classifications",
        format: "records",
        columns: [
          { key: "index", label: "Index", options: [], placeholder: "", required: false },
          {
            key: "value",
            label: "Classified value",
            options: [],
            placeholder: "",
            required: false,
          },
          { key: "label", label: "Assigned label", options: [], placeholder: "", required: false },
        ],
      },
      [
        { index: 0, value: "Refund requested", label: "complaint" },
        { index: 1, value: "Wonderful support", label: "praise" },
      ]
    )
    if (!field) {
      throw new Error("Expected result records to resolve")
    }

    const html = renderToStaticMarkup(createElement(ToolField, { field }))

    expect(html).toContain("Classifications")
    expect(html).toContain("Index")
    expect(html).toContain("Classified value")
    expect(html).toContain("Assigned label")
    expect(html).toContain("Refund requested")
    expect(html).toContain("complaint")
    expect(html).toContain("praise")
    expect(html).toContain("max-h-80")
  })

  it("keeps custom content inside the same labeled well", () => {
    const html = renderToStaticMarkup(
      createElement(
        ToolField,
        { field: { key: "file", label: "File", value: "ignored", format: "text" } },
        createElement("button", { type: "button" }, "Open File")
      )
    )

    expect(html).toContain('data-slot="tool-field-label"')
    expect(html).toContain('data-slot="tool-field-well"')
    expect(html).toContain("aria-labelledby")
    expect(html).toContain("Open File")
    expect(html).not.toContain("ignored")
  })
})

describe("ToolFieldGrid", () => {
  it("uses the shared responsive two-column flow", () => {
    const html = renderToStaticMarkup(
      createElement(ToolFieldGrid, {
        fields: [
          { key: "provider", label: "Provider", value: "Native", format: "text" },
          { key: "active", label: "Active", value: "Yes", format: "boolean" },
        ],
      })
    )

    expect(html).toContain("sm:grid-cols-2")
    expect(html).toContain("Provider")
    expect(html).toContain("Active")
  })
})
