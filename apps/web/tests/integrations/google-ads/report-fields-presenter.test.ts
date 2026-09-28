import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import { googleAdsReportFieldsPresenter } from "@/integrations/google_ads/presenters/report-fields"

describe("Google Ads report-field presenter", () => {
  it("renders field rows, flags, collapsed compatibility counts, and truncation", () => {
    const html = render(
      googleAdsReportFieldsPresenter.render(
        props({
          ...activity("google_ads_list_report_fields"),
          args: { resource: "campaign", search: "cost", limit: 2 },
          result: listResult({
            attribute_resources: ["customer", "campaign_budget"],
            attribute_resource_count: 4,
            compatibility_truncated: true,
            field_count: 6,
            fields: [
              field("campaign.id", "ATTRIBUTE", "INT64"),
              field("campaign.name", "ATTRIBUTE", "STRING", {
                filterable: false,
                is_repeated: true,
                sortable: false,
              }),
            ],
            metric_count: 3,
            metrics: ["metrics.clicks", "metrics.cost_micros"],
            segment_count: 2,
            segments: ["segments.date", "segments.device"],
            truncated: true,
          }),
        })
      )
    )

    expect(html).toContain('aria-label="Google Ads report fields"')
    expect(html).toContain("campaign.id")
    expect(html).toContain("campaign.name")
    expect(html).toContain("2 of 6 fields shown")
    expect(html).toContain("Matches: 6 resource fields, 3 metrics, 2 segments")
  })

  it("renders exact metadata, enum values, selectable-with fields, and raw-name copy actions", () => {
    const html = render(
      googleAdsReportFieldsPresenter.render(
        props({
          ...activity("google_ads_get_report_field"),
          args: { field_names: ["campaign.status", "campaign.id", "campaign.nope"] },
          result: getResult(
            [
              {
                ...field("campaign.status", "ATTRIBUTE", "ENUM"),
                type_url: "google.ads.googleads.v24.enums.CampaignStatusEnum.CampaignStatus",
                enum_values: ["ENABLED", "PAUSED", "REMOVED"],
                selectable_with: ["campaign.id", "campaign.name"],
                attribute_resources: ["customer"],
                metrics: ["metrics.clicks"],
                segments: ["segments.date"],
              },
              detail("campaign.id", "ATTRIBUTE", "INT64"),
            ],
            ["campaign.nope"]
          ),
        })
      )
    )

    expect(html).toContain("Not found: campaign.nope")
    expect(html).toContain("ENABLED")
  })

  it("renders a retry returned to the model as a failure, not a result", () => {
    const listHtml = render(
      googleAdsReportFieldsPresenter.render(
        props({
          ...activity("google_ads_list_report_fields", "failed"),
          args: { resource: "auction_insight", search: "campaign metrics", limit: 100 },
          outcome: "retry",
          result:
            "Google Ads has no report resource named auction_insight. Use a GAQL FROM resource name such as campaign.",
        })
      )
    )
    const getHtml = render(
      googleAdsReportFieldsPresenter.render(
        props({
          ...activity("google_ads_get_report_field", "unknown"),
          args: { field_names: ["campaign.id", "campaign.nope"] },
        })
      )
    )

    expect(listHtml).toContain("has no report resource named auction_insight")
    expect(listHtml).not.toContain("Done")
    expect(getHtml).toContain("Unconfirmed")
  })

  it("falls back for malformed payloads from either tool", () => {
    for (const name of ["google_ads_list_report_fields", "google_ads_get_report_field"]) {
      expect(
        googleAdsReportFieldsPresenter.render(
          props({ ...activity(name), result: { api_version: "v24", fields: "invalid" } })
        )
      ).toBeNull()
    }
  })
})

function activity(name: string, status: ToolActivity["status"] = "completed"): ToolActivity {
  return { id: `${name}-${status}`, kind: status === "running" ? "call" : "result", name, status }
}

function props(value: ToolActivity) {
  return {
    activity: value,
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}

function field(
  name: string,
  category: string,
  dataType: string,
  overrides: Record<string, unknown> = {}
) {
  return {
    name,
    category,
    data_type: dataType,
    selectable: true,
    filterable: true,
    sortable: true,
    is_repeated: false,
    ...overrides,
  }
}

function detail(name: string, category: string, dataType: string) {
  return {
    ...field(name, category, dataType),
    type_url: null,
    enum_values: [],
    selectable_with: [],
    attribute_resources: [],
    metrics: [],
    segments: [],
  }
}

function getResult(fields: Record<string, unknown>[], missing: string[] = []) {
  return { api_version: "v24", fields, missing }
}

function listResult(overrides: Record<string, unknown> = {}) {
  return {
    api_version: "v24",
    resource: "campaign",
    search_matched: true,
    attribute_resources: [],
    attribute_resource_count: 0,
    metrics: ["metrics.clicks"],
    metric_count: 1,
    segments: ["segments.date"],
    segment_count: 1,
    compatibility_truncated: false,
    fields: [field("campaign.id", "ATTRIBUTE", "INT64")],
    field_count: 1,
    truncated: false,
    ...overrides,
  }
}
