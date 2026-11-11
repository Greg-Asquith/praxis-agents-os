// apps/web/tests/integrations/google-ads/shared-helpers.test.ts

import { describe, expect, it } from "vitest"
import {
  parseGoogleAdsMoney,
  parseGoogleAdsUrlList,
} from "@/integrations/google_ads/lib/field-values"

import { parseOutcomeEnvelope, parseOutcomeList } from "@/integrations/google_ads/lib/envelopes"
import {
  countByKind,
  countsPartlyFailed,
  outcomeDetails,
  outcomeTone,
  rowsPartlyFailed,
} from "@/integrations/google_ads/lib/outcomes"
import { parseApprovalAccounts } from "@/integrations/google_ads/lib/accounts"
import { parseAdGroupReference } from "@/integrations/google_ads/lib/ad-groups"
import { parseRecommendationReference } from "@/integrations/google_ads/lib/recommendations"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import { isRecord } from "@/lib/guards"

describe("Google Ads outcome vocabulary", () => {
  it("orders counts and reserves warning for unverified writes", () => {
    expect(
      countByKind([
        { outcome: "failed" },
        { outcome: "added" },
        { outcome: "created" },
        { outcome: "not_found" },
      ])
    ).toEqual([
      { kind: "applied", label: "Applied", count: 2 },
      { kind: "skipped", label: "Skipped", count: 1 },
      { kind: "failed", label: "Failed", count: 1 },
      { kind: "unverified", label: "Unverified", count: 0 },
    ])
    expect(outcomeTone("unverified")).toBe("warning")
    expect(outcomeDetails("Try again", null, "Not confirmed")).toBe("Try again · Not confirmed")
    expect(outcomeDetails(null, null, null)).toBe("")
  })
  it("treats only a mix of failed and other outcomes as partly failed", () => {
    expect(countsPartlyFailed({ updated: 2, failed: 1, unverified: 0 })).toBe(true)
    expect(countsPartlyFailed({ updated: 0, failed: 3 })).toBe(false)
    expect(rowsPartlyFailed([{ outcome: "already_set" }, { outcome: "updated" }])).toBe(false)
  })

  it("keeps advertising acronyms and fallback labels", () => {
    expect(googleAdsTokenLabel("TARGET_CPA_CPC_CPM_CPV_ROAS_ID_URL")).toBe(
      "Target CPA CPC CPM CPV ROAS ID URL"
    )
    expect(googleAdsTokenLabel("__", "Unavailable")).toBe("Unavailable")
  })
})

const outcomes = ["updated", "failed"] as const
function parseRow(value: unknown) {
  return isRecord(value) && typeof value["id"] === "string" ? { id: value["id"] } : null
}
function envelope() {
  return {
    counts: { updated: 1, failed: 0 },
    samples: { updated: [{ id: "1" }], failed: [] },
    samples_truncated: false,
  }
}

describe("Google Ads result envelopes", () => {
  it("parses complete, empty, and truncated evidence", () => {
    expect(parseOutcomeEnvelope(envelope(), outcomes, parseRow)).toEqual({
      counts: { updated: 1, failed: 0 },
      rows: [{ id: "1" }],
      truncated: false,
    })
    expect(
      parseOutcomeEnvelope(
        {
          counts: { updated: 0, failed: 0 },
          samples: { updated: [], failed: [] },
          samples_truncated: false,
        },
        outcomes,
        parseRow
      )?.rows
    ).toEqual([])
    expect(
      parseOutcomeEnvelope(
        { ...envelope(), counts: { updated: 3, failed: 0 }, samples_truncated: true },
        outcomes,
        parseRow
      )?.truncated
    ).toBe(true)
  })
  it.each([
    null,
    { ...envelope(), samples: {} },
    { ...envelope(), samples: { updated: [null], failed: [] } },
  ])("rejects malformed evidence %j", (value) => {
    expect(parseOutcomeEnvelope(value, outcomes, parseRow)).toBeNull()
  })
  it.each([-1, 0.5, "1"])("rejects invalid count %s", (count) => {
    expect(
      parseOutcomeEnvelope(
        { ...envelope(), counts: { updated: count, failed: 0 } },
        outcomes,
        parseRow
      )
    ).toBeNull()
  })
  it("rejects contradictory counts even when aggregate totals match or samples are truncated", () => {
    for (const truncated of [true, false]) {
      expect(
        parseOutcomeEnvelope(
          { ...envelope(), counts: { updated: 0, failed: 1 }, samples_truncated: truncated },
          outcomes,
          parseRow
        )
      ).toBeNull()
    }
    expect(
      parseOutcomeEnvelope({ ...envelope(), counts: { updated: 2, failed: 0 } }, outcomes, parseRow)
    ).toBeNull()
  })
  it("rejects malformed and duplicate list rows", () => {
    const parse = (value: unknown) =>
      parseOutcomeList(value, "campaigns", parseRow, (row) => row.id)
    expect(parse({ campaigns: [{ id: "1" }, { id: "2" }] })).toHaveLength(2)
    expect(parse({ campaigns: [] })).toEqual([])
    for (const value of [
      null,
      {},
      { campaigns: [null] },
      { campaigns: [{ id: "1" }, { id: "1" }] },
    ])
      expect(parse(value)).toBeNull()
  })
})

const adGroup = {
  entity_kind: "google_ads_ad_group",
  customer_id: "1",
  campaign_id: "2",
  ad_group_id: "3",
  label: "Group",
  scope_label: "Campaign",
}
describe("Google Ads reference parsers", () => {
  it("preserves an ad group's labels and rejects another kind of reference", () => {
    expect(parseAdGroupReference(adGroup)).toEqual({
      adGroupId: "3",
      campaignId: "2",
      campaignLabel: "Campaign",
      customerId: "1",
      label: "Group",
    })
    expect(parseAdGroupReference({ ...adGroup, entity_kind: "other" })).toBeNull()
  })
  it("parses recommendation server references", () => {
    expect(
      parseRecommendationReference({
        entity_kind: "google_ads_recommendation",
        customer_id: "1",
        resource_name: "customers/1/recommendations/2",
        recommendation_type: "KEYWORD",
        label: "Add keyword",
      })?.label
    ).toBe("Add keyword")
    expect(parseRecommendationReference({})).toBeNull()
  })
  it("keeps complete account facts and ignores accounts missing a currency or time zone", () => {
    const account = {
      customer_id: "1",
      name: "Account",
      currency: "GBP",
      time_zone: "Europe/London",
    }
    expect([
      ...parseApprovalAccounts([
        account,
        { ...account, customer_id: "2", currency: "bad" },
        { ...account, customer_id: "3", time_zone: "" },
        { ...account, customer_id: "4", name: "   " },
        null,
      ]),
    ]).toEqual([["1", { currencyCode: "GBP", label: "Account", timeZone: "Europe/London" }]])
  })
})

describe("Google Ads shared field values", () => {
  it("validates exact money boundaries without normalizing input", () => {
    expect(parseGoogleAdsMoney("9223372036854.775807")).toBe("9223372036854.775807")
    expect(parseGoogleAdsMoney("9223372036854.775808")).toBeUndefined()
    expect(parseGoogleAdsMoney("0.000001")).toBe("0.000001")
    expect(parseGoogleAdsMoney("0")).toBeUndefined()
    expect(parseGoogleAdsMoney("0", 0n)).toBe("0")
    for (const value of [null, undefined, "", " 1 ", "1.0000001", "-1", 1]) {
      expect(parseGoogleAdsMoney(value)).toBeUndefined()
    }
  })

  it("preserves literal URLs and rejects invalid lists", () => {
    const urls = ["https://example.com/{lpurl}?q=%20"]
    expect(parseGoogleAdsUrlList(urls)).toEqual(urls)
    expect(parseGoogleAdsUrlList([])).toEqual([])
    expect(parseGoogleAdsUrlList(Array.from({ length: 10 }, () => urls[0]))).toHaveLength(10)
    for (const value of [
      null,
      undefined,
      [" https://example.com "],
      ["ftp://example.com"],
      [1],
      ["https://example.com/" + "a".repeat(2048)],
      Array.from({ length: 11 }, () => urls[0]),
    ]) {
      expect(parseGoogleAdsUrlList(value)).toBeUndefined()
    }
  })
})
