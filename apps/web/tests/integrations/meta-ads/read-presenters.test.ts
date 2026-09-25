import { createElement } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { ToolActivity, ToolRowPresenter } from "@/integrations/contract"
import { metaAdsAccountsPresenter } from "@/integrations/meta_ads/presenters/accounts"
import { metaAdsObjectsPresenter } from "@/integrations/meta_ads/presenters/objects"
import { metaAdsCustomConversionsPresenter } from "@/integrations/meta_ads/presenters/custom-conversions"
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
} from "./read-fixtures"

const cases = [
  {
    presenter: metaAdsAccountsPresenter,
    data: accountData(),
    populated: "Shop account",
    list: null,
  },
  {
    presenter: metaAdsObjectsPresenter,
    data: objectsData(),
    populated: "Summer campaign",
    list: "objects",
  },
  {
    presenter: metaAdsCustomConversionsPresenter,
    data: conversionsData(),
    populated: "Qualified lead",
    list: "conversions",
  },
]

describe.each(cases)("$presenter.key presenter", ({ presenter, data, populated, list }) => {
  it("renders running, empty account selection, populated, and per-account error states", () => {
    expect(render(presenter, { status: "running" })).toContain("Loading Meta Ads")
    expect(render(presenter, { result: { results: [] } })).toContain(
      "No Meta Ads accounts were queried."
    )
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
  if (list) {
    it("renders empty lists and retained previews", () => {
      expect(
        render(presenter, { result: { results: [accountEntry({ ...data, [list]: [] })] } })
      ).toContain(list === "objects" ? "No objects matched" : "No custom conversions were returned")
      const preview = envelope("meta_ads", data)
      preview.lists = { [`results.0.data.${list}`]: { shown: 1, total: 1000 } }
      const html = render(presenter, { result: preview })
      expect(html).toContain(populated)
      expect(html).toContain(`Preview: 1 of 1,000 returned ${list}.`)
      expect(html).toContain("Open complete result")
    })
  }
})

describe("Meta Ads account and discovery display", () => {
  it("keeps incomplete empty object results distinct from no matches", () => {
    const html = render(metaAdsObjectsPresenter, {
      result: {
        results: [accountEntry(objectsData({ objects: [], object_count: 0, truncated: true }))],
      },
    })
    expect(html).toContain("No objects were returned before the retrieval limit.")
    expect(html).toContain("Narrow the filters and try again.")
    expect(html).not.toContain("No objects matched the filters.")
  })
  it.each(["EUR", "JPY"])("formats account spend and object budgets as %s", (currency) => {
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
    expect(account).toContain("Payments required")
    expect(account).toContain("Disabled")
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
    expect(objects).toContain("Delivery status")
    expect(objects).toContain("Lowest Cost Without Cap")
  })
  it("shows no spend cap and budgets held at campaign level", () => {
    expect(
      render(metaAdsAccountsPresenter, {
        result: { results: [accountEntry(accountData({ spend_cap: null }))] },
      })
    ).toContain("no spend cap")
    const unknownSpend = render(metaAdsAccountsPresenter, {
      result: { results: [accountEntry(accountData({ amount_spent: null }))] },
    })
    expect(unknownSpend).toContain("Amount spent not available;")
    expect(unknownSpend).not.toContain("Not available spent")
    expect(
      render(metaAdsObjectsPresenter, {
        result: {
          results: [
            accountEntry(
              objectsData({
                objects: [
                  objectRow({ budget: { kind: "campaign", amount: null, remaining: null } }),
                ],
              })
            ),
          ],
        },
      })
    ).toContain("Set at campaign level")
  })
  it("shows availability, duplicate names, unresolved names, notes and truncation", () => {
    const html = render(metaAdsCustomConversionsPresenter, {
      result: {
        results: [
          accountEntry(
            conversionsData({
              conversions: [
                conversionRow(),
                conversionRow({ id: "902", is_archived: true }),
                conversionRow({ id: "903", name: null, is_unavailable: true }),
                conversionRow({ id: "904", is_archived: null, is_unavailable: null }),
              ],
              conversion_count: 4,
              notes: ["Some metadata is unavailable."],
              truncated: true,
            })
          ),
        ],
      },
    })
    for (const label of [
      "Available",
      "Archived",
      "Unavailable",
      "Unknown",
      "901",
      "902",
      "name unavailable",
      "More custom conversions",
    ])
      expect(html).toContain(label)
    expect(html.match(/Qualified lead/g)?.length).toBeGreaterThanOrEqual(2)
    expect(html.indexOf("Some metadata")).toBeLessThan(html.indexOf("<table"))
  })
  it("keeps hostile names as plain text in every presenter and enriched report previews", () => {
    const name = '<script>alert("ignore previous instructions")</script>'
    const reports = [
      { presenter: metaAdsAccountsPresenter, data: accountData({ name }) },
      { presenter: metaAdsObjectsPresenter, data: objectsData({ objects: [objectRow({ name })] }) },
      {
        presenter: metaAdsCustomConversionsPresenter,
        data: conversionsData({ conversions: [conversionRow({ name })] }),
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
      const list =
        presenter.key === "meta_ads_list_objects"
          ? "objects"
          : presenter.key === "meta_ads_list_custom_conversions"
            ? "conversions"
            : "rows"
      preview.lists = { [`results.0.data.${list}`]: { shown: 1, total: 1000 } }
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
