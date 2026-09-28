import { describe, expect, it } from "vitest"

import { formatDataCell } from "@/components/ui/data-table-model"
import { parseMetaAdsInsights } from "@/integrations/meta_ads/lib/insights-model"
import { insightsDetails } from "@/integrations/meta_ads/lib/tool-details"

import { insightsData, insightsRow } from "./fixtures"

describe("Meta Ads Insights model", () => {
  it("keeps keys, metrics, action values, and attribution windows in distinct columns", () => {
    const report = parseMetaAdsInsights(insightsData())
    expect(report?.rows[0]).toMatchObject({
      "keys.campaign_name": "Example campaign",
      "metrics.spend": 125.5,
      "metrics.cpc": null,
      "actions.actions.purchase": 3,
      "actions.actions.purchase.1d_click": 2,
      "actions.actions.purchase.7d_click": 3,
      "actions.action_values.purchase": 450,
    })
    expect(report?.columns.map((column) => column.key)).toEqual([
      "keys.campaign_name",
      "keys.campaign_id",
      "date_start",
      "date_stop",
      "metrics.spend",
      "metrics.ctr",
      "metrics.impressions",
      "metrics.cpc",
      "actions.actions.purchase",
      "actions.actions.purchase.1d_click",
      "actions.actions.purchase.7d_click",
      "actions.action_values.purchase",
    ])
    expect(
      report?.columns.find((column) => column.key === "actions.action_values.purchase")
    ).toMatchObject({ kind: "currency", currencyCode: "EUR" })
  })

  it("keeps text and action columns stable across missing and populated values", () => {
    const report = parseMetaAdsInsights(
      insightsData({
        row_count: 2,
        rows: [
          insightsRow({
            keys: { objective: null, quality_ranking: null },
            metrics: { spend: null },
            actions: { outbound_clicks: [], video_play_actions: [] },
          }),
          insightsRow({
            keys: { objective: "OUTCOME_SALES", quality_ranking: "AVERAGE" },
            metrics: { spend: 125.5 },
            actions: {
              outbound_clicks: [{ action_type: "outbound_click", value: 4, windows: {} }],
              video_play_actions: [{ action_type: "video_view", value: 10, windows: {} }],
            },
          }),
        ],
      })
    )
    expect(report?.columns.map(({ key, kind }) => ({ key, kind }))).toEqual([
      { key: "keys.objective", kind: "text" },
      { key: "keys.quality_ranking", kind: "text" },
      { key: "date_start", kind: "date" },
      { key: "date_stop", kind: "date" },
      { key: "metrics.spend", kind: "currency" },
      { key: "actions.outbound_clicks.outbound_click", kind: "number" },
      { key: "actions.video_play_actions.video_view", kind: "number" },
    ])
    expect(report?.rows[0]?.["keys.objective"]).toBeNull()
    expect(report?.rows[1]).toMatchObject({
      "keys.objective": "OUTCOME_SALES",
      "keys.quality_ranking": "AVERAGE",
      "actions.outbound_clicks.outbound_click": 4,
      "actions.video_play_actions.video_view": 10,
    })
  })

  it.each(["EUR", ""])("formats backend money fields with account currency %j", (currency) => {
    const report = parseMetaAdsInsights(
      insightsData({
        currency,
        money_fields: ["social_spend"],
        rows: [
          insightsRow({
            metrics: { social_spend: 125.5, ctr: 0.5 },
            actions: {
              purchase_roas: [{ action_type: "purchase", value: 2.5, windows: {} }],
            },
          }),
        ],
      })
    )
    const socialSpend = report?.columns.find((column) => column.key === "metrics.social_spend")
    expect(socialSpend).toMatchObject({ kind: "currency", currencyCode: currency })
    if (!socialSpend) throw new Error("Missing social spend column")
    expect(formatDataCell(socialSpend, 125.5)).toBe(
      currency
        ? new Intl.NumberFormat(undefined, { currency, style: "currency" }).format(125.5)
        : "125.5"
    )
    expect(report?.columns.find((column) => column.key === "metrics.ctr")).toMatchObject({
      kind: "percent",
      unit: "percentage-points",
    })
    expect(
      report?.columns.find((column) => column.key === "actions.purchase_roas.purchase")
    ).toMatchObject({
      kind: "number",
    })
  })

  it.each([
    { rows: "bad" },
    { row_count: 1.5 },
    { currency: "not a currency" },
    { since: "2026-02-31" },
    { until: "2026-08-01" },
  ])("rejects malformed report metadata: %j", (override) => {
    expect(parseMetaAdsInsights(insightsData(override))).toBeNull()
  })

  it.each([
    { metrics: { spend: Number.POSITIVE_INFINITY } },
    { actions: { actions: [{ action_type: "purchase", value: 2, windows: { "1d_click": "2" } }] } },
    {
      actions: {
        actions: [
          { action_type: "purchase", value: 2, windows: {} },
          { action_type: "purchase", value: 3, windows: {} },
        ],
      },
    },
  ])("rejects malformed row data: %j", (override) => {
    expect(parseMetaAdsInsights(insightsData({ rows: [insightsRow(override)] }))).toBeNull()
  })

  it("keeps action breakdowns distinct and accepts nullable keys and missing account metadata", () => {
    const report = parseMetaAdsInsights(
      insightsData({
        currency: "",
        timezone_name: "",
        rows: [
          insightsRow({
            keys: { campaign_name: null },
            actions: {
              actions: [
                {
                  action_type: "purchase",
                  value: 2,
                  windows: {},
                  breakdowns: { action_device: "desktop" },
                },
                {
                  action_type: "purchase",
                  value: 3,
                  windows: {},
                  breakdowns: { action_device: "mobile" },
                },
              ],
            },
          }),
        ],
      })
    )
    expect(report?.rows[0]?.["keys.campaign_name"]).toBeNull()
    const columns = report?.columns.filter((column) => column.key.startsWith("actions.")) ?? []
    expect(columns).toHaveLength(2)
    expect(columns.map((column) => report?.rows[0]?.[column.key])).toEqual([2, 3])
    expect(columns.map((column) => column.label).join(" ")).toContain("desktop")
    expect(columns.map((column) => column.label).join(" ")).toContain("mobile")
  })

  it("shows date range, level, breakdowns, and explicit or default attribution", () => {
    expect(
      insightsDetails({
        since: "2026-09-01",
        until: "2026-09-07",
        level: "ad",
        breakdowns: ["age", "gender"],
        attribution_windows: ["1d_click"],
      })
    ).toEqual([
      { label: "Range", value: "2026-09-01 → 2026-09-07" },
      { label: "Level", value: "Ad" },
      { label: "Breakdowns", value: "Age, Gender" },
      { label: "Attribution", value: "1d Click" },
    ])
    expect(insightsDetails({})).toContainEqual({ label: "Attribution", value: "Ad set settings" })
  })
})
