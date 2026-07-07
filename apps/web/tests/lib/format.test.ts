import { describe, expect, it } from "vitest"

import {
  formatBytes,
  formatDateTime,
  initials,
  normalize,
  normalizeOptionalText,
  pluralize,
  titleCaseToken,
  titleFromSegment,
  truncateForPreview,
} from "@/lib/format"

describe("format helpers", () => {
  it("formats byte boundaries", () => {
    expect(formatBytes(1023)).toBe("1023 B")
    expect(formatBytes(1024)).toBe("1.0 KB")
    expect(formatBytes(1024 * 1024)).toBe("1.0 MB")
  })

  it("pluralizes counts", () => {
    expect(pluralize(1, "file")).toBe("file")
    expect(pluralize(2, "file")).toBe("files")
    expect(pluralize(0, "person", "people")).toBe("people")
  })

  it("formats title tokens and route segments", () => {
    expect(titleCaseToken("agent_run-status", "Fallback")).toBe("Agent Run Status")
    expect(titleCaseToken("  ", "Fallback")).toBe("Fallback")
    expect(titleFromSegment("workspace-settings")).toBe("Workspace Settings")
  })

  it("derives initials from names and email-like values", () => {
    expect(initials("Grace Hopper")).toBe("GH")
    expect(initials("ada@example.com")).toBe("AE")
    expect(initials(null)).toBe("PA")
  })

  it("normalizes search and optional text", () => {
    expect(normalize("  Launch Plan  ")).toBe("launch plan")
    expect(normalize("   ")).toBeNull()
    expect(normalize(null)).toBeNull()
    expect(normalizeOptionalText("  Hello  ")).toBe("Hello")
    expect(normalizeOptionalText("   ")).toBeNull()
    expect(normalizeOptionalText(undefined)).toBeNull()
  })

  it("truncates previews only over the limit", () => {
    expect(truncateForPreview(null, 5)).toBeNull()
    expect(truncateForPreview("short", 5)).toBe("short")
    expect(truncateForPreview("longer", 4)).toBe("long...")
  })

  it("keeps date formatting assertions locale-independent", () => {
    expect(formatDateTime(null)).toBe("Never")
    expect(formatDateTime("2026-07-07T10:00:00.000Z")).not.toBe("")
  })
})
