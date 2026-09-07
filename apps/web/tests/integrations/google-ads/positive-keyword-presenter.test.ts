import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { EditedValues } from "@/components/tool-ui/edited-values"
import type { ApprovalDecision } from "@/components/tool-ui/approval-types"
import type { ToolActivity, ToolRowPresenter } from "@/integrations/contract"
import { googleAdsCreatePositiveKeywordsPresenter } from "@/integrations/google_ads/presenters/create-positive-keywords"
import {
  parsePositiveKeywordInput,
  positiveKeywordInputValidationError,
} from "@/integrations/google_ads/lib/positive-keywords"

describe("Google Ads positive keyword input", () => {
  const keyword = (overrides: Record<string, unknown> = {}) => ({
    match_type: "EXACT",
    text: "running shoes",
    ...overrides,
  })

  it("validates CPC micros without floating-point rounding", () => {
    for (const value of ["0.000001", "9223372036854.775807"]) {
      expect(parsePositiveKeywordInput(keyword({ cpc_bid: value }))?.cpcBid).toBe(value)
    }
    for (const value of [
      "0",
      "0.0000001",
      "1.0000000",
      "9223372036854.775808",
      "99999999999999999999",
    ]) {
      expect(parsePositiveKeywordInput(keyword({ cpc_bid: value }))).toBeNull()
    }
  })

  it("enforces URL custom-parameter names, byte limits, count, and case-insensitive uniqueness", () => {
    expect(
      parsePositiveKeywordInput(
        keyword({ url_custom_parameters: { ["a".repeat(16)]: "🙂".repeat(50), constructor: "x" } })
      )?.urlCustomParameters
    ).toEqual({ ["a".repeat(16)]: "🙂".repeat(50), constructor: "x" })
    for (const parameters of [
      { promo_code: "x" },
      { promoCode: "x", promocode: "y" },
      { ["a".repeat(17)]: "x" },
      { key: "🙂".repeat(51) },
      Object.fromEntries(Array.from({ length: 9 }, (_, index) => [`key${String(index)}`, "x"])),
    ]) {
      expect(parsePositiveKeywordInput(keyword({ url_custom_parameters: parameters }))).toBeNull()
      expect(
        positiveKeywordInputValidationError(keyword({ url_custom_parameters: parameters }))
      ).toContain("1-16 ASCII letters or numbers")
    }
  })

  it("requires a final URL when a tracking template is present", () => {
    expect(
      parsePositiveKeywordInput(
        keyword({ tracking_url_template: "https://track.example.com/{lpurl}" })
      )
    ).toBeNull()
    expect(
      parsePositiveKeywordInput(
        keyword({
          final_urls: ["https://example.com"],
          tracking_url_template: "https://track.example.com/{lpurl}",
        })
      )
    ).not.toBeNull()
    expect(
      parsePositiveKeywordInput(keyword({ final_urls: ["https://example.com"] }))
    ).not.toBeNull()
    expect(
      parsePositiveKeywordInput(
        keyword({ final_urls: ["  https://example.com/shoes  "], tracking_url_template: "   " })
      )
    ).toMatchObject({
      finalUrls: ["https://example.com/shoes"],
      trackingUrlTemplate: null,
    })
  })
})

describe("Google Ads positive keyword presenter", () => {
  it("shows selected ad-group labels as failure chips", () => {
    const html = render(
      googleAdsCreatePositiveKeywordsPresenter.render(
        props(
          activity("failed", {
            ad_groups: [adGroup("20", "Shoes", "Search")],
            keywords: [{ text: "running shoes", match_type: "EXACT" }],
          })
        )
      )
    )
    expect(html).toMatch(/data-slot="badge"[^>]*>Shoes/)
  })

  it("groups the approval by campaign and shows trusted account currency", () => {
    const html = render(
      googleAdsCreatePositiveKeywordsPresenter.render(
        props(
          activity("awaiting_approval", {
            _account_currencies: [
              { currency_code: "GBP", customer_id: "1234567890", label: "UK account" },
            ],
            ad_groups: [
              adGroup("10", "Brand exact", "Brand campaign"),
              adGroup("11", "Brand discovery", "Brand campaign"),
            ],
            keywords: [{ match_type: "EXACT", text: "running shoes" }],
          }),
          approvalControls({
            keywords: [
              {
                cpc_bid: "1.25",
                final_mobile_urls: ["https://m.example.com/running"],
                final_url_suffix: "source=ads",
                final_urls: ["https://example.com/running"],
                match_type: "EXACT",
                status: "PAUSED",
                text: "running shoes",
                tracking_url_template: "https://track.example.com/{lpurl}",
                url_custom_parameters: { audience: "runner" },
              },
              { cpc_bid: "", match_type: "PHRASE", text: "trail shoes" },
            ],
          })
        )
      )
    )

    expect(html).toContain("Proposed keyword additions")
    expect(html).toContain("Brand campaign")
    expect(html).toContain("Brand exact")
    expect(html).toContain("Brand discovery")
    expect(html).toContain("UK account")
    expect(html).toContain("GBP")
    expect(html).toContain("Planned additions")
    expect(html).toContain(">4<")
    expect(html).toContain("bid setting, and URL setting")
    expect(html).not.toContain("optional CPC bid")
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Add<\/button>/)
  })

  it("blocks provider-invalid edited keyword rows before approval", () => {
    const validArgs = {
      ad_groups: [adGroup("10", "Brand exact", "Brand campaign")],
      keywords: [{ cpc_bid: "", match_type: "EXACT", text: "running shoes" }],
    }
    const cases = [
      [{ cpc_bid: "9223372036854.775808" }, "CPC bids must be positive"],
      [{ url_custom_parameters: { promo_code: "sale" } }, "1-16 ASCII letters or numbers"],
      [
        { tracking_url_template: "https://track.example.com/{lpurl}" },
        "Add at least one final URL",
      ],
    ] as const

    for (const [override, error] of cases) {
      const malformed = render(
        googleAdsCreatePositiveKeywordsPresenter.render(
          props(
            activity("awaiting_approval", validArgs),
            approvalControls({
              keywords: [{ match_type: "EXACT", text: "running shoes", ...override }],
            })
          )
        )
      )
      expect(malformed).toContain(error)
      expect(malformed).toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Add<\/button>/)
      expect(malformed).toMatch(/<button[^>]*>Decline<\/button>/)
    }
  })

  it("uses the complete serialized keyword column contract", () => {
    const keywordField = positiveKeywordUi().arg_fields[1]

    expect(keywordField).toMatchObject({
      editable: true,
      format: "records",
      key: "keywords",
      label: "Keywords",
      min_rows: 1,
    })
    expect(keywordField && "columns" in keywordField ? keywordField.columns : null).toEqual([
      column("text", "Keyword", { required: true }),
      {
        ...column("match_type", "Match Type", { required: true }),
        options: ["EXACT", "PHRASE", "BROAD"],
      },
      { ...column("status", "Status"), default_value: "ENABLED", options: ["ENABLED", "PAUSED"] },
      column("cpc_bid", "CPC Bid", { secondary: true }),
      column("final_urls", "Final URLs", { format: "list", secondary: true }),
      column("final_mobile_urls", "Final Mobile URLs", { format: "list", secondary: true }),
      column("final_url_suffix", "Final URL Suffix", { secondary: true }),
      column("tracking_url_template", "Tracking URL Template", { secondary: true }),
      column("url_custom_parameters", "URL Custom Parameters", {
        format: "keyvalue",
        max_entries: 8,
        secondary: true,
      }),
    ])
  })

  it("renders the complete keyword table after approval or denial", () => {
    const args = {
      ad_groups: [adGroup("10", "Brand exact", "Brand campaign")],
      keywords: [
        {
          cpc_bid: "",
          final_mobile_urls: [],
          final_url_suffix: "",
          final_urls: [],
          match_type: "EXACT",
          status: "ENABLED",
          text: "running shoes",
          tracking_url_template: "",
          url_custom_parameters: {},
        },
      ],
    }

    for (const decision of ["approved", "denied"] as const) {
      const html = render(
        googleAdsCreatePositiveKeywordsPresenter.render(
          props(activity("awaiting_approval", args), approvalControls({}, decision, true))
        )
      )
      for (const label of [
        "Keyword",
        "Match Type",
        "Status",
        "CPC Bid",
        "Final URLs",
        "Final Mobile URLs",
        "Final URL Suffix",
        "Tracking URL Template",
        "URL Custom Parameters",
      ]) {
        expect(html).toContain(label)
      }
      expect(html).toContain("running shoes")
      expect(html).toContain("—")
      expect(html).not.toContain("<input")
    }
  })

  it("defers Unicode duplicate identity to authoritative backend validation", () => {
    const html = render(
      googleAdsCreatePositiveKeywordsPresenter.render(
        props(
          activity("awaiting_approval", {
            ad_groups: [adGroup("10", "Brand exact", "Brand campaign")],
            keywords: [
              { match_type: "EXACT", text: "Straße" },
              { match_type: "EXACT", text: "STRASSE" },
            ],
          }),
          approvalControls()
        )
      )
    )

    expect(html).not.toContain("edited approval details are invalid")
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Add<\/button>/)
  })

  it("renders backend rows with omitted optional fields", () => {
    const html = render(
      googleAdsCreatePositiveKeywordsPresenter.render(
        props({
          ...activity("completed", null),
          result: {
            results: [
              entry({
                counts: { added: 1, failed: 0, skipped_existing: 0, unverified: 0 },
                currency_code: "GBP",
                samples: {
                  added: [resultRow("added", "trail shoes", "PHRASE", null)],
                  failed: [],
                  skipped_existing: [],
                  unverified: [],
                },
                samples_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("trail shoes")
    expect(html).not.toContain("couldn&#x27;t verify")
  })

  it("rejects contradictory complete result totals", () => {
    const html = render(
      googleAdsCreatePositiveKeywordsPresenter.render(
        props({
          ...activity("completed", null),
          result: {
            results: [
              entry({
                counts: { added: 2, failed: 0, skipped_existing: 0, unverified: 0 },
                currency_code: "GBP",
                samples: {
                  added: [resultRow("added", "shoes", "EXACT", null)],
                  failed: [],
                  skipped_existing: [],
                  unverified: [],
                },
                samples_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("couldn&#x27;t verify")
  })

  it("renders one exportable row per ad-group and keyword pair", () => {
    const html = render(
      googleAdsCreatePositiveKeywordsPresenter.render(
        props({
          ...activity("completed", null),
          result: {
            results: [
              entry({
                counts: { added: 1, failed: 1, skipped_existing: 1, unverified: 1 },
                currency_code: "GBP",
                samples: {
                  added: [resultRow("added", "trail shoes", "PHRASE", "2.5")],
                  failed: [
                    {
                      ...resultRow("failed", "walking shoes", "BROAD", null),
                      error_code: "BID_INCOMPATIBLE_WITH_ADGROUP",
                      message: "The bid is incompatible with this ad group.",
                    },
                  ],
                  skipped_existing: [
                    {
                      ...resultRow("skipped_existing", "running shoes", "EXACT", null),
                      previous_state: "existing",
                      observed: {
                        cpc_bid: "1.25",
                        final_urls: ["https://existing.example.com"],
                        match_type: "EXACT",
                        status: "PAUSED",
                        text: "running shoes",
                      },
                    },
                  ],
                  unverified: [resultRow("unverified", "hiking shoes", "BROAD", null)],
                },
                samples_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Add Keywords")
    expect(html).toContain("trail shoes")
    expect(html).toContain("running shoes")
    expect(html).toContain("walking shoes")
    expect(html).toContain("hiking shoes")
    expect(html).toContain("Already existed")
    expect(html).toContain("Existing keyword")
    expect(html).toContain("Requested Status")
    expect(html).toContain("Existing Status")
    expect(html).toContain("Paused")
    expect(html).toContain("https://existing.example.com")
    expect(html).toContain("Not present")
    expect(html).toMatch(/£2\.50|GBP\s*2\.50/)
    expect(html).toContain("Ad group default")
    expect(html).toContain("The bid is incompatible with this ad group.")
    expect(html).toContain("Download Report CSV")
  })

  it("renders exact bid, URL, tracking, and custom-parameter request evidence", () => {
    const html = render(
      googleAdsCreatePositiveKeywordsPresenter.render(
        props({
          ...activity("completed", null),
          result: {
            results: [
              entry({
                counts: { added: 1, failed: 0, skipped_existing: 0, unverified: 0 },
                currency_code: "GBP",
                samples: {
                  added: [
                    {
                      ...resultRow("added", "trail shoes", "PHRASE", "2.5"),
                      requested: {
                        ...resultRow("added", "trail shoes", "PHRASE", "2.5").requested,
                        final_urls: ["https://example.com/trail"],
                        final_mobile_urls: ["https://m.example.com/trail"],
                        final_url_suffix: "source=ads",
                        tracking_url_template: "https://track.example.com/{lpurl}",
                        url_custom_parameters: [{ key: "audience", value: "trail" }],
                      },
                    },
                  ],
                  failed: [],
                  skipped_existing: [],
                  unverified: [],
                },
                samples_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(html).toMatch(/CPC.*£2\.50|CPC.*GBP\s*2\.50/)
    expect(html).toContain("https://example.com/trail")
    expect(html).toContain("https://track.example.com/{lpurl}")
    expect(html).toContain("{_audience}=trail")
  })

  it("keeps denied, loading, malformed, and unverified states distinct", () => {
    const denied = activity("denied", {
      ad_groups: [adGroup("10", "Brand exact", "Brand campaign")],
      keywords: [
        {
          cpc_bid: "",
          final_mobile_urls: [],
          final_url_suffix: "",
          final_urls: [],
          match_type: "EXACT",
          status: "ENABLED",
          text: "running shoes",
          tracking_url_template: "",
          url_custom_parameters: {},
        },
      ],
    })
    denied.decisionReason = "Use a different match type."
    const deniedHtml = render(googleAdsCreatePositiveKeywordsPresenter.render(props(denied)))
    const loadingHtml = render(
      googleAdsCreatePositiveKeywordsPresenter.render(props(activity("running", null)))
    )
    const malformedHtml = render(
      googleAdsCreatePositiveKeywordsPresenter.render(
        props({ ...activity("completed", null), result: { results: [entry({ bad: true })] } })
      )
    )
    const unverifiedHtml = render(
      googleAdsCreatePositiveKeywordsPresenter.render(
        props({
          ...activity("completed", null),
          result: {
            results: [
              {
                ...entry(null),
                error_code: "unverified_mutation",
                error_message: "provider transport detail",
                status: "error",
              },
            ],
          },
        })
      )
    )

    expect(deniedHtml).toContain("declined")
    expect(deniedHtml).toContain("Use a different match type.")
    expect(deniedHtml).not.toContain("Failed")
    expect(loadingHtml).toContain("Adding Google Ads keywords…")
    expect(malformedHtml).toContain("couldn&#x27;t verify")
    expect(unverifiedHtml).toContain("couldn&#x27;t verify whether Google Ads added")
    expect(unverifiedHtml).not.toContain("provider transport detail")
  })
})

function activity(status: ToolActivity["status"], args: unknown): ToolActivity {
  return {
    args,
    id: `google_ads_create_keywords:${status}`,
    kind: "approval",
    name: "google_ads_create_keywords",
    status,
  }
}

function props(
  value: ToolActivity,
  approvalDecision?: Parameters<ToolRowPresenter["render"]>[0]["approvalDecision"]
) {
  return {
    activity: value,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
    ui: positiveKeywordUi(),
  }
}

function adGroup(adGroupId: string, label: string, campaignLabel: string) {
  return {
    ad_group_id: adGroupId,
    campaign_id: "5",
    customer_id: "1234567890",
    entity_kind: "google_ads_ad_group",
    label,
    scope_label: campaignLabel,
    version: 1,
  }
}

function resultRow(
  outcome: "added" | "failed" | "skipped_existing" | "unverified",
  text: string,
  matchType: "BROAD" | "EXACT" | "PHRASE",
  cpcBid: string | null
) {
  return {
    ad_group_id: "10",
    ad_group_name: "Brand exact",
    campaign_id: "5",
    campaign_name: "Brand campaign",
    ...(outcome === "added" ? { external_ref: "customers/1234567890/adGroupCriteria/10~90" } : {}),
    outcome,
    previous_state: "absent",
    requested: {
      ...(cpcBid === null ? {} : { cpc_bid: cpcBid, cpc_bid_micros: "2500000" }),
      match_type: matchType,
      status: "ENABLED",
      text,
    },
  }
}

function entry(data: unknown) {
  return {
    data,
    display_name: "UK account",
    error_message: null,
    external_id: "1234567890",
    provider_key: "google_ads",
    status: "success",
  }
}

function approvalControls(
  edits: EditedValues = {},
  decision: ApprovalDecision["decision"] = "pending",
  disabled = false
) {
  return {
    decision: {
      decision,
      edits,
      message: decision === "denied" ? "Use a different match type." : "",
    } as ApprovalDecision,
    disabled,
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    pendingCount: 1,
    submitting: false,
  }
}

function positiveKeywordUi() {
  const field = (key: string, label: string, format: "entity_list" | "records") => ({
    editable: true,
    format,
    key,
    label,
    min_rows: 1,
    options: [],
    placeholder: "",
    secondary: false,
  })
  return {
    approval_prompt: "Review",
    approval_title: "Add Keywords",
    approve_label: "Approve & Add",
    arg_fields: [
      { ...field("ad_groups", "Ad Groups", "entity_list"), entity_kind: "google_ads_ad_group" },
      {
        ...field("keywords", "Keywords", "records"),
        columns: [
          column("text", "Keyword", { required: true }),
          {
            ...column("match_type", "Match Type", { required: true }),
            key: "match_type",
            label: "Match Type",
            options: ["EXACT", "PHRASE", "BROAD"],
          },
          {
            ...column("status", "Status"),
            default_value: "ENABLED",
            options: ["ENABLED", "PAUSED"],
          },
          column("cpc_bid", "CPC Bid", { secondary: true }),
          column("final_urls", "Final URLs", { format: "list", secondary: true }),
          column("final_mobile_urls", "Final Mobile URLs", {
            format: "list",
            secondary: true,
          }),
          column("final_url_suffix", "Final URL Suffix", { secondary: true }),
          column("tracking_url_template", "Tracking URL Template", { secondary: true }),
          column("url_custom_parameters", "URL Custom Parameters", {
            format: "keyvalue",
            max_entries: 8,
            secondary: true,
          }),
        ],
      },
    ],
    completed_label: "Added Keywords",
    failed_label: "Couldn't Add Keywords",
    icon: "google_ads",
    result_fields: [],
    running_label: "Adding Keywords",
  }
}

function column(
  key: string,
  label: string,
  overrides: Partial<{
    format: "keyvalue" | "list" | "number" | "text"
    max_entries: number | null
    required: boolean
    secondary: boolean
  }> = {}
) {
  return {
    default_value: null,
    format: "text" as const,
    key,
    label,
    max_entries: null,
    options: [],
    placeholder: "",
    required: false,
    secondary: false,
    ...overrides,
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
