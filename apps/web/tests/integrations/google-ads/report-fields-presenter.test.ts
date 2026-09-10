import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import { googleAdsReportFieldsPresenter } from "@/integrations/google_ads/presenters/report-fields"

describe("Google Ads report-field presenter", () => {
  it("matches both report-field tools and renders their running states", () => {
    expect(
      googleAdsReportFieldsPresenter.matches(activity("google_ads_list_report_fields", "running"))
    ).toBe(true)
    expect(
      googleAdsReportFieldsPresenter.matches(activity("google_ads_get_report_field", "running"))
    ).toBe(true)

    const listHtml = render(
      googleAdsReportFieldsPresenter.render(
        props(activity("google_ads_list_report_fields", "running"))
      )
    )
    const getHtml = render(
      googleAdsReportFieldsPresenter.render(
        props(activity("google_ads_get_report_field", "running"))
      )
    )

    expect(listHtml).toContain("List Google Ads Report Fields")
    expect(listHtml).toContain("Listing Google Ads report field metadata")
    expect(getHtml).toContain("Get Google Ads Report Field")
    expect(getHtml).toContain("Getting Google Ads report field metadata")
  })

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
    expect(html).toContain("Data type")
    expect(html).toContain("Selectable")
    expect(html).toContain("Filterable")
    expect(html).toContain("Sortable")
    expect(html).toContain("Repeated")
    expect(html).toContain("2 of 6 fields shown")
    expect(html).toContain("Search: cost")
    expect(html).toContain("Matches: 6 resource fields, 3 metrics, 2 segments")
    expect(html).toContain("One or more compatibility lists are shortened")
    expect(html).toContain("Attribute resources")
    expect(html).toContain("2 of 4")
    expect(html).toContain("Metrics")
    expect(html).toContain("2 of 3")
    expect(html).toContain("Segments")
    expect(html).toContain("Download Report CSV")
    expect(html).toContain('aria-label="Copy Resource"')
    expect(html).toContain("customer")
    expect(html).not.toContain("<details open=")
  })

  it("renders an empty field result without discarding compatibility metadata", () => {
    const html = render(
      googleAdsReportFieldsPresenter.render(
        props({
          ...activity("google_ads_list_report_fields"),
          result: listResult({
            fields: [],
            field_count: 0,
            metrics: [],
            metric_count: 0,
            segments: [],
            segment_count: 0,
          }),
        })
      )
    )

    expect(html).toContain("No resource fields were returned")
    expect(html).toContain("No compatible metrics returned")
    expect(html).toContain("No compatible segments returned")
  })

  it("explains when no search term matched and the whole catalog is shown", () => {
    const html = render(
      googleAdsReportFieldsPresenter.render(
        props({
          ...activity("google_ads_list_report_fields"),
          args: { resource: "shared_criterion", search: "nothing here", limit: 50 },
          result: listResult({
            resource: "shared_criterion",
            search_matched: false,
            fields: [field("shared_criterion.keyword.text", "ATTRIBUTE", "STRING")],
            field_count: 1,
          }),
        })
      )
    )

    expect(html).toContain("Matches: No matches, all shown")
    expect(html).toContain("Nothing matched “nothing here”")
    expect(html).toContain("shared_criterion.keyword.text")
  })

  it("distinguishes successful metric searches from calls with no matches", () => {
    const metricsHtml = render(
      googleAdsReportFieldsPresenter.render(
        props({
          ...activity("google_ads_list_report_fields"),
          args: { resource: "campaign", search: "metrics.a", limit: 100 },
          result: listResult({
            fields: [],
            field_count: 0,
            metrics: ["metrics.average_cost"],
            metric_count: 76,
            segments: [],
            segment_count: 0,
            truncated: true,
          }),
        })
      )
    )
    const noMatchesHtml = render(
      googleAdsReportFieldsPresenter.render(
        props({
          ...activity("google_ads_list_report_fields"),
          args: { resource: "campaign", search: "metrics.d", limit: 100 },
          result: listResult({
            fields: [],
            field_count: 0,
            metrics: [],
            metric_count: 0,
            segments: [],
            segment_count: 0,
          }),
        })
      )
    )

    expect(metricsHtml).toContain("Search: metrics.a")
    expect(metricsHtml).toContain("Matches: 76 metrics")
    expect(metricsHtml).toContain("No resource fields matched “metrics.a”")
    expect(noMatchesHtml).toContain("Search: metrics.d")
    expect(noMatchesHtml).toContain("Matches: No matches")
    expect(noMatchesHtml).not.toContain("Fields: 0")
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

    expect(html).toContain('aria-label="Google Ads report field metadata"')
    expect(html).toContain("campaign.status")
    expect(html).toContain('aria-label="campaign.id metadata"')
    expect(html).toContain("Fields: campaign.status, campaign.id")
    expect(html).toContain("Not found: campaign.nope")
    expect(html).toContain("Not found in Google Ads")
    expect(html).toContain('aria-label="Copy API name"')
    expect(html).toContain("Enum values")
    expect(html).toContain("Selectable with")
    expect(html).toContain("3")
    expect(html).toContain("2")
    expect(html).toContain("Type URL")
    expect(html).toContain("Yes")
    expect(html).toContain("No")
    expect(html).toContain("ENABLED")
    expect(html).toContain('aria-label="Copy Enum values"')
    expect(html).not.toContain("<details open=")
  })

  it("renders complete exact metadata lists beyond the list-tool limit", () => {
    const enumValues = Array.from({ length: 101 }, (_, index) => `VALUE_${String(index)}`)
    const html = render(
      googleAdsReportFieldsPresenter.render(
        props({
          ...activity("google_ads_get_report_field"),
          result: getResult([
            {
              ...field("campaign.status", "ATTRIBUTE", "ENUM"),
              type_url: null,
              enum_values: enumValues,
              selectable_with: [],
              attribute_resources: ["customer"],
              metrics: ["metrics.clicks"],
              segments: ["segments.date"],
            },
          ]),
        })
      )
    )

    expect(html).toContain("Not found: None")
    expect(html).not.toContain("Not found in Google Ads")
    expect(html).toContain("101")
    expect(html).toContain("VALUE_100")
    expect(html).not.toContain("limited to 100 values")
    expect(html).toContain("Not provided")
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
