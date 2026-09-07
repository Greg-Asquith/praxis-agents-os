import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import googleAdsModule from "@/integrations/google_ads"
import { googleAdsWriteCopy } from "@/integrations/google_ads/lib/copy"

const cases = [
  {
    name: "google_ads_create_keywords",
    spec: { verb: "Add", object: "keywords", effect: "added" },
  },
  {
    name: "google_ads_remove_keywords",
    spec: { verb: "Remove", object: "keywords", effect: "removed" },
  },
  {
    name: "google_ads_update_device_bid_modifiers",
    spec: {
      verb: "Update",
      object: "device bid adjustments",
      effect: "updated",
    },
  },
  {
    name: "google_ads_update_keywords",
    spec: { verb: "Update", object: "keywords", effect: "updated" },
  },
  {
    name: "google_ads_create_campaign_budget",
    spec: { verb: "Create", object: "campaign budget", effect: "created" },
  },
  {
    name: "google_ads_remove_campaign_budgets",
    spec: {
      verb: "Remove",
      object: "campaign budgets",
      effect: "removed",
      destructive: true,
    },
  },
  {
    name: "google_ads_link_negative_keyword_list",
    spec: {
      verb: "Update",
      object: "campaign shared list",
      effect: "updated",
    },
  },
  {
    name: "google_ads_create_negative_keyword_list",
    spec: {
      verb: "Create",
      object: "negative keyword lists",
      effect: "created",
    },
  },
  {
    name: "google_ads_assign_campaign_budgets",
    spec: { verb: "Assign", object: "campaign budgets", effect: "assigned" },
  },
  {
    name: "google_ads_update_campaign_budget_amounts",
    spec: {
      verb: "Update",
      object: "campaign budget amounts",
      effect: "updated",
    },
  },
  {
    name: "google_ads_update_campaign_status",
    spec: { verb: "Update", object: "campaign status", effect: "updated" },
  },
  {
    name: "google_ads_dismiss_recommendations",
    spec: { verb: "Dismiss", object: "recommendations", effect: "dismissed" },
  },
  {
    name: "google_ads_apply_recommendations",
    spec: { verb: "Apply", object: "recommendations", effect: "applied" },
  },
  {
    name: "google_ads_add_campaign_negative_keywords",
    spec: {
      verb: "Add",
      object: "campaign negative keywords",
      effect: "added",
    },
  },
  {
    name: "google_ads_remove_campaign_negative_keywords",
    spec: {
      verb: "Remove",
      object: "campaign negative keywords",
      effect: "removed",
    },
  },
  {
    name: "google_ads_add_negative_keywords",
    spec: { verb: "Add", object: "negative keywords", effect: "added" },
  },
  {
    name: "google_ads_remove_negative_keywords",
    spec: { verb: "Remove", object: "negative keywords", effect: "removed" },
  },
  {
    name: "google_ads_add_ad_group_negative_keywords",
    spec: {
      verb: "Add",
      object: "ad group negative keywords",
      effect: "added",
    },
  },
  {
    name: "google_ads_remove_ad_group_negative_keywords",
    spec: {
      verb: "Remove",
      object: "ad group negative keywords",
      effect: "removed",
    },
  },
] as const

const sources = import.meta.glob("/src/integrations/google_ads/presenters/**/*.tsx", {
  eager: true,
  query: "?raw",
  import: "default",
})

function markup(name: string, status: ToolActivity["status"], result?: unknown) {
  const activity: ToolActivity = {
    id: "copy-fixture",
    name,
    status,
    kind: "result",
    args: {},
    result,
  }
  const presenters = googleAdsModule.toolRowPresenters.filter((item) => item.matches(activity))
  expect(presenters).toHaveLength(1)
  const presenter = presenters[0]
  if (!presenter) throw new Error("Missing Google Ads write presenter")
  return renderToStaticMarkup(
    createElement(
      "div",
      null,
      presenter.render({
        activity,
        compact: false,
        defaultOpen: true,
        live: false,
        providerKey: "google_ads",
      })
    )
  )
}

function escape(value: string) {
  return renderToStaticMarkup(createElement("span", null, value)).slice(6, -7)
}

function entry(status: string, data: unknown) {
  return {
    provider_key: "google_ads",
    display_name: "Account",
    external_id: "1234567890",
    status,
    data,
    error_message: null,
  }
}

describe("Google Ads registered write copy", () => {
  it("covers every declared write variant and every registered write presenter", () => {
    const names = Object.values(sources).flatMap((source) =>
      [...source.matchAll(/(google_ads_\w+): defineGoogleAdsWriteVariant/g)].map(
        (match) => match[1]
      )
    )
    expect(cases.map((item) => item.name).sort()).toEqual(names.sort())
    const covered = googleAdsModule.toolRowPresenters.filter((presenter) =>
      cases.some(({ name }) =>
        presenter.matches({ id: "coverage", name, status: "running", kind: "call", args: {} })
      )
    )
    expect(covered.map((item) => item.key).sort()).toEqual(
      googleAdsModule.toolRowPresenters
        .filter((item) => item.handlesApprovals)
        .map((item) => item.key)
        .sort()
    )
  })

  it.each(cases)("uses shared lifecycle wording for $name", ({ name, spec }) => {
    const copy = googleAdsWriteCopy(spec)
    const running =
      name === "google_ads_link_negative_keyword_list"
        ? googleAdsWriteCopy({ verb: "Link", object: "campaign shared list", effect: "linked" })
            .progressLabel
        : copy.progressLabel
    const denied =
      name === "google_ads_dismiss_recommendations"
        ? "This dismissal was declined. The recommendations remain visible in Google Ads."
        : copy.deniedDescription
    const states: [string, string][] = [
      [markup(name, "running"), running],
      [markup(name, "awaiting_approval"), copy.waitingLabel],
      [markup(name, "denied"), denied],
      [markup(name, "failed"), copy.failedDescription],
      [markup(name, "unknown"), copy.failedDescription],
      [markup(name, "completed", null), copy.resultFailure],
      [markup(name, "completed", { results: [entry("success", {})] }), copy.malformedDescription],
      [
        markup(name, "completed", {
          results: [{ ...entry("error", null), error_code: "unverified_mutation" }],
        }),
        copy.unverifiedDescription,
      ],
    ]
    for (const [html, description] of states) {
      expect(html).toContain(escape(copy.heading))
      expect(html).toContain(escape(description))
    }
    for (const [html] of states.slice(5)) {
      expect(html).toContain("Check Google Ads before taking further action.")
    }
    expect(markup(name, "completed", { results: [] })).toContain(escape(copy.emptyLabel))
  })
})
