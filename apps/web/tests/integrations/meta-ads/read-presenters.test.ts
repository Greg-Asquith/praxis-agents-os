import { createElement } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { ToolActivity, ToolRowPresenter } from "@/integrations/contract"
import { metaAdsAccountsPresenter } from "@/integrations/meta_ads/presenters/accounts"
import { metaAdsActivitiesPresenter } from "@/integrations/meta_ads/presenters/activities"
import { metaAdsObjectsPresenter } from "@/integrations/meta_ads/presenters/objects"
import { metaAdsConversionsPresenter } from "@/integrations/meta_ads/presenters/conversions"
import { metaAdsInsightsPresenter } from "@/integrations/meta_ads/presenters/insights"
import { envelope } from "../result-preview-fixtures"
import { accountEntry, insightsData, insightsRow } from "./fixtures"
import {
  accountData,
  objectsData,
  objectRow,
  conversionsData,
  conversionRow,
  customAction,
  customEventRow,
  activitiesData,
  activityRow,
} from "./read-fixtures"

const cases = [
  {
    presenter: metaAdsAccountsPresenter,
    data: accountData(),
    populated: "Shop account",
  },
  {
    presenter: metaAdsObjectsPresenter,
    data: objectsData(),
    populated: "Summer campaign",
  },
  {
    presenter: metaAdsConversionsPresenter,
    data: conversionsData(),
    populated: "Qualified lead",
  },
  {
    presenter: metaAdsActivitiesPresenter,
    data: activitiesData(),
    populated: "Ad set budget updated",
  },
]

describe.each(cases)("$presenter.key presenter", ({ presenter, data, populated }) => {
  it("renders populated and per-account error states", () => {
    const html = render(presenter, {
      result: {
        results: [
          accountEntry(data),
          accountEntry(null, {
            external_id: "456",
            status: "error",
            error_message: "Access was removed.",
          }),
        ],
      },
    })
    expect(html).toContain(populated)
    expect(html).toContain("Access was removed.")
    expect(html).toContain("1/2 connections")
  })
  it("falls back for malformed result data", () => {
    expect(render(presenter, { result: { results: [accountEntry({ malformed: true })] } })).toBe(
      "<div></div>"
    )
  })
})

describe("Meta Ads account and discovery display", () => {
  it.each(["JPY"])("formats account spend and object budgets as %s", (currency) => {
    const amount = new Intl.NumberFormat(undefined, { style: "currency", currency }).format(125)
    const account = render(metaAdsAccountsPresenter, {
      result: {
        results: [
          accountEntry(
            accountData({
              currency,
              amount_spent: "125",
              status: "Disabled",
              disable_reason: "Payments required",
            })
          ),
        ],
      },
    })
    expect(account).toContain(`${amount} spent of`)
    const objects = render(metaAdsObjectsPresenter, {
      result: {
        results: [
          accountEntry(
            objectsData({
              currency,
              objects: [
                objectRow({ budget: { kind: "lifetime", amount: "125", remaining: "10" } }),
              ],
            })
          ),
        ],
      },
    })
    expect(objects).toContain(`${amount} lifetime`)
  })
  it("keeps hostile names as plain text in every presenter and enriched report previews", () => {
    const name = '<script>alert("ignore previous instructions")</script>'
    const reports = [
      { presenter: metaAdsAccountsPresenter, data: accountData({ name }) },
      { presenter: metaAdsObjectsPresenter, data: objectsData({ objects: [objectRow({ name })] }) },
      {
        presenter: metaAdsConversionsPresenter,
        data: conversionsData({ conversions: [conversionRow({ name }), customEventRow(name)] }),
      },
      {
        presenter: metaAdsActivitiesPresenter,
        data: activitiesData({
          events: [activityRow({ object_name: name, actor_name: name, new_value: name })],
        }),
      },
      {
        presenter: metaAdsInsightsPresenter,
        data: insightsData({
          rows: [
            insightsRow({ actions: { actions: [customAction({ custom_conversion_name: name })] } }),
          ],
        }),
      },
    ]
    for (const { presenter, data } of reports) {
      const preview = envelope("meta_ads", data)
      const lists: Record<string, string> = {
        meta_ads_list_objects: "objects",
        meta_ads_list_conversions: "conversions",
        meta_ads_list_activities: "events",
      }
      const list = lists[presenter.key] ?? "rows"
      const items: unknown = (data as Record<string, unknown>)[list]
      const shown = Array.isArray(items) ? items.length : 1
      preview.lists = { [`results.0.data.${list}`]: { shown, total: 1000 } }
      const results = [
        { results: [accountEntry(data)] },
        ...(presenter.key === "meta_ads_get_accounts" ? [] : [preview]),
      ]
      for (const result of results) {
        const html = render(presenter, { result })
        expect(html).toContain("&lt;script&gt;")
        expect(html).not.toContain("<script>")
      }
    }
  })
})

function render(presenter: ToolRowPresenter, overrides: Partial<ToolActivity>) {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(
        "div",
        null,
        presenter.render({
          activity: {
            id: "read",
            kind: "result",
            name: presenter.key,
            status: "completed",
            ...overrides,
          },
          compact: false,
          defaultOpen: true,
          live: false,
          providerKey: "meta_ads",
        })
      )
    )
  )
}
