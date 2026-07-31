import { describe, expect, it } from "vitest"

import { normalizeRecord } from "@/lib/guards"

describe("normalizeRecord", () => {
  it("returns records and parses JSON object strings", () => {
    const record = { name: "report.md" }

    expect(normalizeRecord(record)).toBe(record)
    expect(normalizeRecord('{"name":"report.md"}')).toEqual(record)
  })

  it("rejects non-record values and malformed JSON", () => {
    expect(normalizeRecord(null)).toBeNull()
    expect(normalizeRecord(["report.md"])).toBeNull()
    expect(normalizeRecord('["report.md"]')).toBeNull()
    expect(normalizeRecord("not-json")).toBeNull()
  })
})
