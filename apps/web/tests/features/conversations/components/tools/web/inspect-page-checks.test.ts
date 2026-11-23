// apps/web/tests/features/conversations/components/tools/web/inspect-page-checks.test.ts

import { describe, expect, it } from "vitest"

import { pageChecks } from "@/features/conversations/components/tools/web/inspect-page-checks"
import type { InspectedPage } from "@/features/conversations/components/tools/web/inspect-page-result"

const META = {
  canonical: "https://a.example",
  description: "Plans and prices for every team.",
  language: "en",
  metaRefresh: null,
  robots: "noindex, follow",
  title: "x".repeat(61),
  viewport: "width=device-width",
}

describe("pageChecks", () => {
  it("puts problems first and matches a canonical without its trailing slash", () => {
    const page: InspectedPage = {
      headings: { h1Count: 2, items: [] },
      images: { items: [], missingAlt: 0, total: 3 },
      links: null,
      looksClientRendered: false,
      meta: META,
      structuredData: [{ content: "{", truncated: false, types: [], valid: false }],
      tags: null,
      wordCount: 120,
    }

    const checks = pageChecks(page, "https://a.example/")
    const tones = checks.map((check) => check.tone)

    expect(tones.slice(0, 4)).toEqual(["warning", "warning", "warning", "warning"])
    expect(tones.slice(4)).not.toContain("warning")
    expect(checks.find((check) => check.label.startsWith("Canonical"))?.tone).toBe("pass")
  })
})
