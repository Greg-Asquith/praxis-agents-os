import { describe, expect, it } from "vitest"
import {
  parseMetaAdsAccount,
  parseMetaAdsActivities,
  parseMetaAdsObjects,
  parseMetaAdsConversions,
} from "@/integrations/meta_ads/lib/read-models"
import { parseMetaAdsInsights } from "@/integrations/meta_ads/lib/insights-model"
import {
  accountData,
  objectsData,
  objectRow,
  conversionsData,
  conversionRow,
  customAction,
  activitiesData,
  activityRow,
} from "./read-fixtures"
import { insightsData, insightsRow } from "./fixtures"

describe("Meta Ads account and discovery models", () => {
  it("parses nullable account fields and exact major-unit money", () => {
    expect(parseMetaAdsAccount(accountData())).toEqual(accountData())
    expect(
      parseMetaAdsAccount(
        accountData({
          name: null,
          disable_reason: "Payments required",
          balance: null,
          spend_cap: null,
          timezone_name: null,
        })
      )
    ).not.toBeNull()
  })
  it.each([{ amount_spent: 12 }, { spend_cap: "1e99" }, { status: "x".repeat(513) }])(
    "rejects malformed accounts %j",
    (override) => {
      expect(parseMetaAdsAccount(accountData(override))).toBeNull()
    }
  )
  it.each(["campaign"])("parses %s budgets", (kind) => {
    const data = objectsData({
      objects: [objectRow({ budget: { kind, amount: null, remaining: null } })],
    })
    expect(parseMetaAdsObjects(data)).toEqual(data)
  })
  it.each([
    { object_count: 1.1 },
    { objects: [objectRow({ budget: { kind: "daily", amount: 100, remaining: null } })] },
    { objects: [objectRow({ start_time: "yesterday" })] },
  ])("rejects malformed objects %j", (override) => {
    expect(parseMetaAdsObjects(objectsData(override))).toBeNull()
  })
  it("keeps duplicate conversion names distinct and accepts unavailable metadata", () => {
    const data = conversionsData({
      conversions: [
        conversionRow(),
        conversionRow({ id: "902", is_archived: true }),
        conversionRow({
          id: "903",
          name: null,
          description: null,
          is_archived: null,
          is_unavailable: null,
        }),
      ],
      conversion_count: 3,
    })
    expect(parseMetaAdsConversions(data)).toEqual(data)
  })
  it.each([{ conversion_count: 0 }, { conversions: [conversionRow({ is_unavailable: "true" })] }])(
    "rejects malformed conversions %j",
    (override) => {
      expect(parseMetaAdsConversions(conversionsData(override))).toBeNull()
    }
  )
})

describe("Meta Ads change history model", () => {
  it("parses events with nullable provider text and window notes", () => {
    const data = activitiesData({
      events: [
        activityRow(),
        activityRow({
          event_type: null,
          translated_event_type: null,
          object_type: null,
          object_id: null,
          object_name: null,
          actor_name: null,
          old_value: null,
          new_value: null,
        }),
      ],
      event_count: 2,
      truncated: true,
      window_note: "Some changes in this window may be missing.",
    })
    expect(parseMetaAdsActivities(data)).toEqual(data)
  })
  it.each([
    { event_count: 0 },
    { events: [activityRow({ event_time: "last Tuesday" })] },
    { events: [activityRow({ object_id: "act_1" })] },
    { events: [activityRow({ old_value: "x".repeat(257) })] },
  ])("rejects malformed change history %j", (override) => {
    expect(parseMetaAdsActivities(activitiesData(override))).toBeNull()
  })
})

describe("Meta Ads custom conversion report columns", () => {
  it("preserves IDs, numbers, windows and breakdowns with duplicate resolved names", () => {
    const report = parseMetaAdsInsights(
      insightsData({
        rows: [
          insightsRow({
            actions: {
              actions: [
                customAction(),
                customAction({
                  action_type: "offsite_conversion.custom.902",
                  custom_conversion_id: "902",
                  value: 7,
                }),
              ],
              action_values: [customAction({ value: 15.5 })],
              cost_per_action_type: [customAction({ value: 2.5 })],
            },
          }),
        ],
      })
    )
    const columns = report?.columns.filter((column) => column.key.startsWith("actions.")) ?? []
    expect(columns).toHaveLength(8)
    expect(columns.map((column) => column.label).join(" ")).toContain("Qualified lead (ID: 901)")
    expect(columns.map((column) => column.label).join(" ")).toContain("Qualified lead (ID: 902)")
    expect(columns.every((column) => column.label.includes("Action Device: mobile"))).toBe(true)
    expect(columns.map((column) => report?.rows[0]?.[column.key])).toEqual([
      3, 2, 7, 2, 15.5, 2, 2.5, 2,
    ])
    expect(columns.filter((column) => column.kind === "currency")).toHaveLength(4)
  })
  it("uses explicit unresolved labels including older retained actions", () => {
    for (const overrides of [
      { custom_conversion_name: null },
      { custom_conversion_name: undefined, custom_conversion_id: undefined },
    ]) {
      const report = parseMetaAdsInsights(
        insightsData({ rows: [insightsRow({ actions: { actions: [customAction(overrides)] } })] })
      )
      expect(report?.columns.map((column) => column.label).join(" ")).toContain(
        "Custom conversion (name unavailable) (ID: 901)"
      )
    }
  })
  it.each([{ custom_conversion_id: "bad" }, { custom_conversion_id: "999" }])(
    "rejects malformed custom conversion identity %j",
    (override) => {
      expect(
        parseMetaAdsInsights(
          insightsData({ rows: [insightsRow({ actions: { actions: [customAction(override)] } })] })
        )
      ).toBeNull()
    }
  )
})
