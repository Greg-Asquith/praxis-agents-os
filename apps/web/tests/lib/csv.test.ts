import { describe, expect, it } from "vitest"

import { parseCsv } from "@/lib/csv"

describe("parseCsv", () => {
  it("parses quoted delimiters, escaped quotes, and multiline fields", () => {
    expect(parseCsv('name,notes\r\nPraxis,"first line\nsecond ""quoted"" line"')).toEqual([
      ["name", "notes"],
      ["Praxis", 'first line\nsecond "quoted" line'],
    ])
  })

  it("stops after the requested row limit", () => {
    expect(parseCsv("one\ntwo\nthree", 2)).toEqual([["one"], ["two"]])
  })
})
