import { describe, expect, it } from "vitest"

import {
  formatBytes,
  formatCompactDate,
  formatCurrencyAmount,
  formatDuration,
  formatPercentageChange,
  microsToCurrencyUnits,
} from "@/lib/format"

describe("format helpers", () => {
  it("formats byte boundaries", () => {
    expect(formatBytes(1023)).toBe("1023 B")
    expect(formatBytes(1024)).toBe("1.0 KB")
    expect(formatBytes(1024 * 1024)).toBe("1.0 MB")
  })

  it("converts micros to currency units", () => {
    expect(microsToCurrencyUnits(1)).toBe(0.000001)
    expect(microsToCurrencyUnits(12_500_000)).toBe(12.5)
  })

  it("formats decimal currency amounts and percentage changes", () => {
    expect(formatCurrencyAmount("12.345678", "GBP")).toMatch(/£12\.345678|GBP\s*12\.345678/)
    expect(formatCurrencyAmount("1000000000.000001", "GBP")).toBe("GBP 1000000000.000001")
    expect(formatPercentageChange(10, 15)).toBe("+50%")
    expect(formatPercentageChange(10, 8)).toBe("-20%")
    expect(formatPercentageChange(0, 8)).toBe("—")
  })

  it("formats durations without rolling seconds up to 60", () => {
    expect(formatDuration(90500, "milliseconds")).toBe("1 min 31 sec")
    expect(formatDuration(119.9)).toBe("2 min")
  })

  it("formats compact dates by local calendar age", () => {
    const now = new Date(2026, 6, 16, 12)
    const today = new Date(2026, 6, 16, 17, 21)
    const thisYear = new Date(2026, 6, 7, 10)
    const priorYear = new Date(2025, 11, 31, 23, 50)

    expect(formatCompactDate(null, now)).toBe("Never")
    expect(formatCompactDate(undefined, now)).toBe("Never")
    expect(formatCompactDate(today.toISOString(), now)).toBe(
      new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(today)
    )
    expect(formatCompactDate(thisYear.toISOString(), now)).toBe(
      new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(thisYear)
    )
    expect(formatCompactDate(priorYear.toISOString(), now)).toBe(
      new Intl.DateTimeFormat(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
      }).format(priorYear)
    )
  })

  it("formats yesterday at 23:50 as a date instead of a time", () => {
    const now = new Date(2026, 6, 16, 0, 10)
    const yesterday = new Date(2026, 6, 15, 23, 50)

    expect(formatCompactDate(yesterday.toISOString(), now)).toBe(
      new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(yesterday)
    )
  })
})
