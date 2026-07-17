// apps/web/tests/features/conversations/components/tool-field.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ToolField, ToolFieldGrid } from "@/features/conversations/components/tool-field"

describe("ToolField", () => {
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
