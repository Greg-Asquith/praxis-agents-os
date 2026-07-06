// apps/web/src/features/conversations/tool-ui.test.ts

import { describe, expect, it } from "vitest"

import {
  autoUiFields,
  friendlyResultText,
  humanizeKey,
  resolveToolTemplate,
  resolveUiFields,
} from "@/features/conversations/tool-ui"

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
        { key: "name", label: "File name", format: "text" },
        { key: "missing", label: "Missing", format: "text" },
        { key: "confirmed", label: "Confirmed", format: "boolean" },
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
      [{ key: "query", label: "Search", format: "text" }],
      JSON.stringify({ query: "praxis" })
    )
    expect(fields).toEqual([{ key: "query", label: "Search", value: "praxis", format: "text" }])
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
