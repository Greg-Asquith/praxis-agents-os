import { describe, expect, it } from "vitest"
import {
  campaignNegativeKeywordResult,
  adGroupNegativeKeywordResult,
} from "@/integrations/google_ads/presenters/negative-keywords/utils"

describe.each([false, true])("scoped negative keywords removing=%s", (removing) => {
  describe.each(["campaign", "ad_group"] as const)("%s targets", (scope) => {
    const applied = removing ? "removed" : "added"
    const skipped = removing ? "not_found" : "skipped_existing"
    const parse = (value: unknown) =>
      scope === "campaign"
        ? campaignNegativeKeywordResult(value, removing)
        : adGroupNegativeKeywordResult(value, removing)
    const counts = { [applied]: 1, [skipped]: 1, failed: 1 }
    const outcome = (text: string, result: string, matchType = "EXACT") => ({
      text,
      match_type: matchType,
      outcome: result,
    })
    function target() {
      return {
        [`${scope}_id`]: "1",
        [`${scope}_name`]: "Target",
        campaign_name: "Campaign",
        counts: { ...counts },
        errors_truncated: false,
        [`${scope}_errors`]: [
          { text: "failed", match_type: "EXACT", message: "Rejected", error_code: "REJECTED" },
        ],
        keyword_outcomes: [
          outcome("applied", applied),
          outcome("skipped", skipped),
          outcome("failed", "failed"),
        ],
      }
    }
    const envelope = (rows: unknown[] = [target()], totals = counts, truncated = false) => ({
      counts: totals,
      [`${scope}s`]: rows,
      [`${scope}s_truncated`]: truncated,
    })
    it("accepts exact mixed outcomes and retains totals", () => {
      expect(parse(envelope())?.totals).toEqual({ applied: 1, skipped: 1, failed: 1 })
    })
    it.each([
      "wrong action",
      "wrong skipped action",
      "duplicate keyword",
      "duplicate case",
      "empty text",
      "ANY mutation",
      "exact count",
      "error count",
    ])("rejects %s evidence", (defect) => {
      const row = target()
      if (defect === "wrong action")
        row.keyword_outcomes[0] = outcome("applied", removing ? "added" : "removed")
      if (defect === "wrong skipped action")
        row.keyword_outcomes[1] = outcome("skipped", removing ? "skipped_existing" : "not_found")
      if (defect === "duplicate keyword") row.keyword_outcomes[1] = outcome("applied", skipped)
      if (defect === "duplicate case") row.keyword_outcomes[1] = outcome("APPLIED", skipped)
      if (defect === "empty text") row.keyword_outcomes[0] = outcome(" ", applied)
      if (defect === "ANY mutation") row.keyword_outcomes[0] = outcome("applied", applied, "ANY")
      if (defect === "exact count") row.counts[applied] = 2
      if (defect === "error count") row[`${scope}_errors`] = []
      expect(parse(envelope([row], row.counts))).toBeNull()
    })
    it("rejects duplicate targets and contradictory aggregate counts", () => {
      expect(
        parse(envelope([target(), target()], { [applied]: 2, [skipped]: 2, failed: 2 }))
      ).toBeNull()
      expect(parse(envelope([target()], { ...counts, [applied]: 2 }))).toBeNull()
      expect(parse(envelope([target()], { ...counts, [applied]: 0 }, true))).toBeNull()
    })
    it("preserves legacy aggregates and independent target/error truncation", () => {
      const { keyword_outcomes: omitted, ...legacy } = target()
      expect(omitted).toHaveLength(3)
      const result = parse(envelope([legacy]))
      expect(result?.totals).toEqual({ applied: 1, skipped: 1, failed: 1 })
      const rows = result && ("campaigns" in result ? result.campaigns : result.adGroups)
      expect(rows?.[0]?.keywordOutcomes).toBeNull()
      expect(parse(envelope([legacy], { ...counts, [applied]: 3 }, true))).not.toBeNull()
      expect(
        parse(envelope([{ ...legacy, errors_truncated: true, [`${scope}_errors`]: [] }]))
      ).not.toBeNull()
      expect(
        parse(
          envelope([
            {
              ...legacy,
              errors_truncated: true,
              [`${scope}_errors`]: [
                { text: "a", match_type: "EXACT", message: "Error", error_code: "ERROR" },
                { text: "b", match_type: "EXACT", message: "Error", error_code: "ERROR" },
              ],
            },
          ])
        )
      ).toBeNull()
    })
    it("retains multiple concrete effects for the same keyword text", () => {
      const row = target()
      row.keyword_outcomes.push(outcome("applied", applied, "PHRASE"))
      row.counts[applied] = 2
      expect(parse(envelope([row], row.counts))?.totals.applied).toBe(2)
    })
    it("preserves concrete match variants and allows ANY only for removal misses", () => {
      const row = target()
      row.keyword_outcomes = [
        outcome("same", applied),
        outcome("same", skipped, removing ? "ANY" : "PHRASE"),
        outcome("same", "failed", "BROAD"),
      ]
      expect(parse(envelope([row]))).not.toBeNull()
      row.keyword_outcomes[0] = outcome("same", applied, "ANY")
      expect(parse(envelope([row]))).toBeNull()
    })
  })
})
