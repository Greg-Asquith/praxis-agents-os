import { describe, expect, it } from "vitest"

import {
  isDateTimeString,
  isNonNegativeInteger,
  isNullableString,
  isPositiveInteger,
  normalizeRecord,
} from "@/lib/guards"

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

describe("numeric and date guards", () => {
  it("distinguishes non-negative and positive integers", () => {
    expect(isNonNegativeInteger(0)).toBe(true)
    expect(isPositiveInteger(0)).toBe(false)
    expect(isPositiveInteger(1)).toBe(true)

    for (const value of [-1, 1.5, Number.NaN, "1", null]) {
      expect(isNonNegativeInteger(value)).toBe(false)
      expect(isPositiveInteger(value)).toBe(false)
    }
  })

  it("accepts parseable date-time strings only", () => {
    expect(isDateTimeString("2026-08-14T10:00:00Z")).toBe(true)
    expect(isDateTimeString("not-a-date")).toBe(false)
    expect(isDateTimeString(0)).toBe(false)
  })

  it("accepts strings and explicit null for nullable string fields", () => {
    expect(isNullableString("value")).toBe(true)
    expect(isNullableString(null)).toBe(true)
    expect(isNullableString(undefined)).toBe(false)
  })
})
