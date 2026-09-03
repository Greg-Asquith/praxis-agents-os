import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { EditedValues } from "@/components/tool-ui/edited-values"
import type { ToolActivity, ToolRowPresenter } from "@/integrations/contract"
import { googleAdsAddPositiveKeywordsPresenter } from "@/integrations/google_ads/presenters/add-positive-keywords"

describe("Google Ads positive keyword presenter", () => {
  it("groups the approval by campaign and shows trusted account currency", () => {
    const html = render(
      googleAdsAddPositiveKeywordsPresenter.render(
        props(
          activity("awaiting_approval", {
            _account_currencies: [
              { currency_code: "GBP", customer_id: "1234567890", label: "UK account" },
            ],
            ad_groups: [
              adGroup("10", "Brand exact", "Brand campaign"),
              adGroup("11", "Brand discovery", "Brand campaign"),
            ],
            keywords: [
              { cpc_bid: "1.25", match_type: "EXACT", text: "running shoes" },
              { cpc_bid: "", match_type: "PHRASE", text: "trail shoes" },
            ],
          }),
          approvalControls()
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
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Add<\/button>/)
  })

  it("blocks malformed and duplicate edited keyword rows", () => {
    const validArgs = {
      ad_groups: [adGroup("10", "Brand exact", "Brand campaign")],
      keywords: [{ cpc_bid: "", match_type: "EXACT", text: "running shoes" }],
    }
    const malformed = render(
      googleAdsAddPositiveKeywordsPresenter.render(
        props(
          activity("awaiting_approval", validArgs),
          approvalControls({
            keywords: [
              { cpc_bid: "", match_type: "EXACT", text: "running shoes" },
              { cpc_bid: "", match_type: "EXACT", text: "RUNNING SHOES" },
            ],
          })
        )
      )
    )

    expect(malformed).toContain("edited approval details are invalid")
    expect(malformed).toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Add<\/button>/)
    expect(malformed).toMatch(/<button[^>]*>Decline<\/button>/)
  })

  it("renders backend rows with omitted optional fields", () => {
    const html = render(
      googleAdsAddPositiveKeywordsPresenter.render(
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
      googleAdsAddPositiveKeywordsPresenter.render(
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
      googleAdsAddPositiveKeywordsPresenter.render(
        props({
          ...activity("completed", null),
          result: {
            results: [
              entry({
                counts: { added: 1, failed: 1, skipped_existing: 1, unverified: 0 },
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
                    },
                  ],
                  unverified: [],
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
    expect(html).toContain("Already exists")
    expect(html).toContain("Existing keyword")
    expect(html).toContain("Not present")
    expect(html).toMatch(/£2\.50|GBP\s*2\.50/)
    expect(html).toContain("Ad group default")
    expect(html).toContain("The bid is incompatible with this ad group.")
    expect(html).toContain("Download Report CSV")
  })

  it("keeps denied, loading, malformed, and unverified states distinct", () => {
    const denied = activity("denied", {
      ad_groups: [adGroup("10", "Brand exact", "Brand campaign")],
      keywords: [{ match_type: "EXACT", text: "running shoes" }],
    })
    denied.decisionReason = "Use a different match type."
    const deniedHtml = render(googleAdsAddPositiveKeywordsPresenter.render(props(denied)))
    const loadingHtml = render(
      googleAdsAddPositiveKeywordsPresenter.render(props(activity("running", null)))
    )
    const malformedHtml = render(
      googleAdsAddPositiveKeywordsPresenter.render(
        props({ ...activity("completed", null), result: { results: [entry({ bad: true })] } })
      )
    )
    const unverifiedHtml = render(
      googleAdsAddPositiveKeywordsPresenter.render(
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
    id: `google_ads_add_keywords:${status}`,
    kind: "approval",
    name: "google_ads_add_keywords",
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
    ...(cpcBid === null ? {} : { cpc_bid: cpcBid, cpc_bid_micros: "2500000" }),
    ...(outcome === "added" ? { external_ref: "customers/1234567890/adGroupCriteria/10~90" } : {}),
    match_type: matchType,
    outcome,
    previous_state: "absent",
    text,
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

function approvalControls(edits: EditedValues = {}) {
  return {
    decision: { decision: "pending" as const, edits, message: "" as const },
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
          { key: "text", label: "Keyword", options: [], placeholder: "", required: true },
          {
            key: "match_type",
            label: "Match Type",
            options: ["EXACT", "PHRASE", "BROAD"],
            placeholder: "",
            required: true,
          },
          { key: "cpc_bid", label: "CPC Bid", options: [], placeholder: "", required: false },
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

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
