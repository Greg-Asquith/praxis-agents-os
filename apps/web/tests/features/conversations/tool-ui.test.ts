// apps/web/tests/features/conversations/tool-ui.test.ts

import { describe, expect, it } from "vitest"

import {
  autoUiFields,
  editableUiFields,
  friendlyResultText,
  humanizeKey,
  resolveToolTemplate,
  resolveUiFields,
} from "@/features/conversations/tool-ui"
import type { ToolUiField } from "@/features/tools/types"

function uiField(field: Pick<ToolUiField, "key" | "label"> & Partial<ToolUiField>): ToolUiField {
  return {
    format: "text",
    editable: false,
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

  it("prefers earlier sources over later ones", () => {
    const resolved = resolveToolTemplate("Wrote {name}", [{ name: "draft.md" }, { name: "x" }])
    expect(resolved).toBe("Wrote draft.md")
  })

  it("returns null when any placeholder cannot be resolved", () => {
    expect(resolveToolTemplate("Writing {name}", [{}])).toBeNull()
    expect(resolveToolTemplate("Writing {name}", [null, undefined])).toBeNull()
  })

  it("ignores non-scalar values", () => {
    expect(resolveToolTemplate("Writing {name}", [{ name: { nested: true } }])).toBeNull()
  })

  it("truncates long values", () => {
    const resolved = resolveToolTemplate("Searching for {query}", [{ query: "q".repeat(100) }])
    expect(resolved).toBe(`Searching for ${"q".repeat(64)}…`)
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

describe("editableUiFields", () => {
  const fields = [
    uiField({ key: "query", label: "Search", editable: true }),
    uiField({ key: "provider", label: "Provider" }),
    uiField({ key: "limit", label: "Limit", editable: true }),
  ] as const

  it("returns only editable fields backed by string arguments", () => {
    expect(
      editableUiFields([...fields], { query: "Praxis", provider: "openai", limit: 10 })
    ).toEqual([fields[0]])
  })

  it("returns no fields for non-record arguments", () => {
    expect(editableUiFields([...fields], "not structured")).toEqual([])
  })
})

describe("autoUiFields", () => {
  it("builds humanized fields from scalar entries only", () => {
    const fields = autoUiFields({ file_name: "a.md", max_bytes: 10, nested: { skip: true } })
    expect(fields).toEqual([
      { key: "file_name", label: "File name", value: "a.md", format: "text" },
      { key: "max_bytes", label: "Max bytes", value: "10", format: "text" },
    ])
  })
})

describe("friendlyResultText", () => {
  it("returns plain string results", () => {
    expect(friendlyResultText("All done")).toBe("All done")
  })

  it("rejects JSON-looking or non-string results", () => {
    expect(friendlyResultText('{"a":1}')).toBeNull()
    expect(friendlyResultText({ a: 1 })).toBeNull()
  })
})

describe("humanizeKey", () => {
  it("converts snake case and camel case to sentence case", () => {
    expect(humanizeKey("file_name")).toBe("File name")
    expect(humanizeKey("maxBytes")).toBe("Max bytes")
  })
})
