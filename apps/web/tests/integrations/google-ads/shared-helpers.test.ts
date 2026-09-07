import { describe, expect, it } from "vitest"
import {
  parseGoogleAdsMoney,
  parseGoogleAdsUrlList,
  parseGoogleAdsCustomParameters,
} from "@/integrations/google_ads/lib/field-values"

import { approvalCountLine, googleAdsWriteCopy } from "@/integrations/google_ads/lib/copy"
import { parseOutcomeEnvelope, parseOutcomeList } from "@/integrations/google_ads/lib/envelopes"
import {
  countByKind,
  outcomeDetails,
  outcomeKind,
  outcomeLabel,
  outcomeTone,
} from "@/integrations/google_ads/lib/outcomes"
import {
  campaignBudgetIdentity,
  parseCampaignBudgetReference,
} from "@/integrations/google_ads/lib/campaign-budgets"
import { parseAccountCurrencies } from "@/integrations/google_ads/lib/accounts"
import { parseAdGroupReference } from "@/integrations/google_ads/lib/ad-groups"
import { parseCampaignReference } from "@/integrations/google_ads/lib/campaigns"
import {
  parseKeywordRow,
  parseNegativeListReference,
} from "@/integrations/google_ads/lib/negative-keywords"
import { parsePositiveKeywordReference } from "@/integrations/google_ads/lib/positive-keywords"
import { parseRecommendationReference } from "@/integrations/google_ads/lib/recommendations"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import { isNullableFiniteNumber, isRecord } from "@/lib/guards"

describe("Google Ads outcome vocabulary", () => {
  it.each([
    "updated",
    "created",
    "assigned",
    "removed",
    "linked",
    "unlinked",
    "applied",
    "dismissed",
    "added",
  ] as const)("classifies %s as applied", (token) => {
    expect(outcomeKind(token)).toBe("applied")
    expect(outcomeLabel(token)).toBe(token.charAt(0).toUpperCase() + token.slice(1))
  })
  it.each([
    ["already_set", "Already set"],
    ["already_exists", "Already existed"],
    ["already_linked", "Already linked"],
    ["not_linked", "Not linked"],
    ["already_dismissed", "Already dismissed"],
    ["skipped_existing", "Already existed"],
    ["not_found", "Not found"],
  ] as const)("classifies %s as skipped", (token, label) => {
    expect(outcomeKind(token)).toBe("skipped")
    expect(outcomeLabel(token)).toBe(label)
  })
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
    expect([
      outcomeTone("applied"),
      outcomeTone("skipped"),
      outcomeTone("failed"),
      outcomeTone("unverified"),
    ]).toEqual(["success", undefined, "danger", "warning"])
    expect(outcomeKind("failed")).toBe("failed")
    expect(outcomeLabel("unverified")).toBe("Unverified")
    expect(outcomeDetails("Try again", null, "Not confirmed")).toBe("Try again · Not confirmed")
    expect(outcomeDetails(null, null, null)).toBe("")
  })
  it("keeps advertising acronyms and fallback labels", () => {
    expect(googleAdsTokenLabel("TARGET_CPA_CPC_CPM_CPV_ROAS_ID_URL")).toBe(
      "Target CPA CPC CPM CPV ROAS ID URL"
    )
    expect(googleAdsTokenLabel("__", "Unavailable")).toBe("Unavailable")
  })
})

describe("Google Ads lifecycle copy", () => {
  it("pins every shell field", () => {
    expect(
      googleAdsWriteCopy({
        verb: "Update",
        object: "campaign status",
        objectPlural: "campaign statuses",
        effect: "changed",
      })
    ).toEqual({
      heading: "Update Campaign Status",
      approval: {
        label: "Update Google Ads Campaign Status",
        title: "Update Campaign Status",
        approveLabel: "Approve & Update",
      },
      progressLabel: "Updating Google Ads campaign status…",
      waitingLabel: "Waiting for campaign status approval…",
      deniedDescription: "This campaign status change was declined. Nothing was changed.",
      failedDescription: "The update did not finish. No campaign status change was confirmed.",
      emptyLabel: "No Google Ads accounts changed campaign statuses.",
      malformedDescription:
        "The system couldn't verify this account's campaign status outcomes. Check Google Ads before taking further action.",
      resultFailure:
        "The system couldn't verify the campaign status changes. Check Google Ads before taking further action.",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads changed campaign statuses. Check Google Ads before taking further action.",
      resultAriaLabel: "Google Ads campaign status results",
      unconfirmedAriaLabel: "Unconfirmed Google Ads campaign status change",
    })
    expect(
      googleAdsWriteCopy({
        verb: "Remove",
        object: "budgets",
        effect: "removed",
        destructive: true,
      }).approval.title
    ).toBe("Permanently remove budgets")
    expect(approvalCountLine(1, "campaign")).toBe("1 campaign")
    expect(approvalCountLine(0, "keyword")).toBe("0 keywords")
    expect(approvalCountLine(12, "recommendation")).toBe("12 recommendations")
  })
  it.each([
    ["Create", "Creating"],
    ["Assign", "Assigning"],
    ["Remove", "Removing"],
    ["Link", "Linking"],
    ["Unlink", "Unlinking"],
    ["Apply", "Applying"],
    ["Dismiss", "Dismissing"],
    ["Add", "Adding"],
  ] as const)("conjugates %s", (verb, progress) => {
    expect(googleAdsWriteCopy({ verb, object: "keywords", effect: "changed" }).progressLabel).toBe(
      `${progress} Google Ads keywords…`
    )
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
    {},
    { ...envelope(), counts: {} },
    { ...envelope(), samples: {} },
    { ...envelope(), samples_truncated: 1 },
    { ...envelope(), samples: { updated: [null], failed: [] } },
  ])("rejects malformed evidence %j", (value) => {
    expect(parseOutcomeEnvelope(value, outcomes, parseRow)).toBeNull()
  })
  it.each([-1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1, "1"])(
    "rejects invalid count %s",
    (count) => {
      expect(
        parseOutcomeEnvelope(
          { ...envelope(), counts: { updated: count, failed: 0 } },
          outcomes,
          parseRow
        )
      ).toBeNull()
    }
  )
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
  it.each([null, 0, -1, 1.5])("accepts nullable finite number %s", (value) => {
    expect(isNullableFiniteNumber(value)).toBe(true)
  })
  it.each([undefined, NaN, Infinity, "1", false])("rejects invalid nullable number %s", (value) => {
    expect(isNullableFiniteNumber(value)).toBe(false)
  })
})

const campaign = { entity_kind: "google_ads_campaign", campaign_id: "1", label: " " }
const budget = {
  entity_kind: "google_ads_campaign_budget",
  customer_id: "1",
  budget_id: "2",
  label: "Budget",
  amount_micros: "000123",
  currency_code: "GBP",
}
const adGroup = {
  entity_kind: "google_ads_ad_group",
  customer_id: "1",
  campaign_id: "2",
  ad_group_id: "3",
  label: "Group",
  scope_label: "Campaign",
}
const keyword = {
  entity_kind: "google_ads_keyword",
  customer_id: "1",
  campaign_id: "2",
  ad_group_id: "3",
  criterion_id: "4",
  label: "",
  text: "Example",
  match_type: "EXACT",
  cpc_bid_micros: "1234567",
}

describe("Google Ads reference parsers", () => {
  it("preserves campaign, budget, ad-group, and keyword labels and exact amounts", () => {
    expect(parseCampaignReference(campaign)).toEqual({ campaignId: "1", label: "1" })
    const parsed = parseCampaignBudgetReference(budget)
    expect(parsed?.amountMicros).toBe("123")
    expect(parsed && campaignBudgetIdentity(parsed)).toBe("1:2")
    expect(parseAdGroupReference(adGroup)).toEqual({
      adGroupId: "3",
      campaignId: "2",
      campaignLabel: "Campaign",
      customerId: "1",
      label: "Group",
    })
    expect(parsePositiveKeywordReference(keyword)).toMatchObject({
      identity: "1:3:4",
      label: "Example",
      cpcBid: "1.234567",
      scopeLabel: "Campaign and ad group unavailable",
    })
    expect(parsePositiveKeywordReference({ ...keyword, cpc_bid_micros: "0" })?.cpcBid).toBe("0")
  })
  it.each([
    null,
    {},
    { ...campaign, entity_kind: "other" },
    { ...campaign, campaign_id: 1 },
    { ...campaign, campaign_id: "abc" },
  ])("rejects invalid campaign references %j", (value) => {
    expect(parseCampaignReference(value)).toBeNull()
  })
  it("rejects malformed budget and keyword metadata", () => {
    for (const patch of [
      { currency_code: "gbp" },
      { amount_micros: 1.5 },
      { reference_count: -1 },
      { explicitly_shared: "true" },
    ])
      expect(parseCampaignBudgetReference({ ...budget, ...patch })).toBeNull()
    for (const patch of [
      { criterion_id: "abc" },
      { entity_kind: "other" },
      { cpc_bid_micros: "9223372036854775808" },
      { bid_modifier: Infinity },
    ])
      expect(parsePositiveKeywordReference({ ...keyword, ...patch })).toBeNull()
    expect(parseAdGroupReference({ ...adGroup, entity_kind: "other" })).toBeNull()
  })
  it("parses recommendation and negative-list server references", () => {
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
    expect(
      parseNegativeListReference({
        entity_kind: "google_ads_shared_set",
        customer_id: "1",
        shared_set_id: "2",
      })
    ).toEqual({ customerId: "1", listId: "2", label: "Selected negative keyword list" })
    expect(parseNegativeListReference({ customer_id: "1", shared_set_id: "bad" })).toBeNull()
  })
  it("preserves keyword row match types and optional ANY", () => {
    expect(parseKeywordRow({ text: "example", match_type: "EXACT" })).toEqual({
      text: "example",
      matchType: "EXACT",
    })
    expect(parseKeywordRow({ text: "example", match_type: "ANY" })).toBeNull()
    expect(parseKeywordRow({ text: "example", match_type: "ANY" }, true)?.matchType).toBe("ANY")
  })
  it("keeps valid account currencies and ignores unavailable metadata", () => {
    expect([
      ...parseAccountCurrencies([
        { customer_id: "1", label: "Account", currency_code: "GBP" },
        { customer_id: "2", label: "Other", currency_code: "bad" },
        null,
      ]),
    ]).toEqual([["1", { currencyCode: "GBP", label: "Account" }]])
    expect(parseAccountCurrencies(undefined).size).toBe(0)
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

  it("validates parameter byte limits and case-insensitive uniqueness in both shapes", () => {
    expect(parseGoogleAdsCustomParameters({ Campaign: "é".repeat(100) })).toEqual({
      Campaign: "é".repeat(100),
    })
    expect(parseGoogleAdsCustomParameters([{ key: "Campaign", value: " literal " }])).toEqual({
      Campaign: " literal ",
    })
    for (const value of [
      null,
      undefined,
      { Campaign: "é".repeat(101) },
      { Campaign: "one", campaign: "two" },
      [
        { key: "Campaign", value: "one" },
        { key: "Campaign", value: "two" },
      ],
      { invalid_name: "value" },
      { ["a".repeat(17)]: "value" },
      { key: 1 },
      Object.fromEntries(Array.from({ length: 9 }, (_, index) => [String(index), "value"])),
    ]) {
      expect(parseGoogleAdsCustomParameters(value)).toBeUndefined()
    }
  })
})
