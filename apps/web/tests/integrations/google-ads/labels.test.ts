import { describe, expect, it } from "vitest"

import {
  isLabelReference,
  labelDraftsValidationError,
  parseLabelDrafts,
} from "@/integrations/google_ads/lib/labels"

describe("Google Ads label drafts", () => {
  it("blocks approval for names, colours, and duplicates Google Ads would reject", () => {
    const error = (labels: unknown[]) => {
      const drafts = parseLabelDrafts(labels)
      return drafts ? labelDraftsValidationError(drafts) : "unparsed"
    }

    expect(error([{ name: "  Black   Friday ", background_color: "#abc" }])).toBeNull()
    expect(error([{ name: "x".repeat(81) }])).toMatch(/80 characters/)
    expect(error([{ name: "Q4", background_color: "orange" }])).toMatch(/colour/)
    expect(error([{ name: "Q4" }, { name: "q4" }])).toMatch(/different name/)
  })

  it("counts code points and folds case like the server", () => {
    const error = (labels: unknown[]) => labelDraftsValidationError(parseLabelDrafts(labels) ?? [])

    expect(error([{ name: "\u{1F600}".repeat(80) }])).toBeNull()
    expect(error([{ name: "Straße" }, { name: "STRASSE" }])).toMatch(/different name/)
  })

  it("accepts only label references with valid identifiers", () => {
    expect(
      isLabelReference({ entity_kind: "google_ads_label", customer_id: "111", label_id: "8" })
    ).toBe(true)
    expect(isLabelReference({})).toBe(false)
    expect(
      isLabelReference({ entity_kind: "google_ads_campaign", customer_id: "111", label_id: "8" })
    ).toBe(false)
  })
})
