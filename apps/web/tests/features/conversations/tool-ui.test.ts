import { describe, expect, it } from "vitest"

import { resolveToolTemplate, resolveUiFields } from "@/features/conversations/tool-ui"
import type { ToolUiField } from "@/features/tools/types"

function uiField(field: Pick<ToolUiField, "key" | "label"> & Partial<ToolUiField>): ToolUiField {
  return {
    format: "text",
    editable: false,
    min_rows: 0,
    placeholder: "",
    options: [],
    secondary: false,
    ...field,
  }
}

describe("resolveToolTemplate", () => {
  it("fills placeholders from the first source that has the key", () => {
    const resolved = resolveToolTemplate("Writing {name}", [{ name: "report.md" }, {}])
    expect(resolved).toBe("Writing report.md")
  })

  it("returns null when any placeholder cannot be resolved", () => {
    expect(resolveToolTemplate("Writing {name}", [{}])).toBeNull()
    expect(resolveToolTemplate("Writing {name}", [null, undefined])).toBeNull()
  })
})
describe("resolveUiFields", () => {
  it("resolves declared fields and drops missing ones", () => {
    const fields = resolveUiFields(
      [
        uiField({ key: "name", label: "File name" }),
        uiField({ key: "missing", label: "Missing" }),
        uiField({ key: "confirmed", label: "Confirmed", format: "boolean" }),
      ],
      { name: "report.md", confirmed: true }
    )
    expect(fields).toEqual([
      { key: "name", label: "File name", value: "report.md", format: "text" },
      { key: "confirmed", label: "Confirmed", value: "Yes", format: "boolean" },
    ])
  })

  it("parses JSON string sources", () => {
    const fields = resolveUiFields(
      [uiField({ key: "query", label: "Search", editable: true })],
      JSON.stringify({ query: "praxis" })
    )
    expect(fields).toEqual([{ key: "query", label: "Search", value: "praxis", format: "text" }])
  })

  it("resolves scalar lists with display text and individual items", () => {
    const fields = resolveUiFields([uiField({ key: "items", label: "Items", format: "list" })], {
      items: ["alpha", 2, "gamma"],
    })

    expect(fields).toEqual([
      {
        key: "items",
        label: "Items",
        value: "alpha, 2, gamma",
        format: "list",
        items: ["alpha", "2", "gamma"],
      },
    ])
  })

  it("accepts only HTTP URLs", () => {
    const fields = [uiField({ key: "link", label: "Link", format: "url" })]

    expect(resolveUiFields(fields, { link: "https://praxis-agents.ai/docs" })).toEqual([
      {
        key: "link",
        label: "Link",
        value: "https://praxis-agents.ai/docs",
        format: "url",
      },
    ])
    expect(resolveUiFields(fields, { link: "javascript:alert(1)" })).toEqual([])
    expect(resolveUiFields(fields, { link: "not a URL" })).toEqual([])
  })
})
