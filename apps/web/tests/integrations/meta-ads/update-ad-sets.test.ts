// apps/web/tests/integrations/meta-ads/update-ad-sets.test.ts

import { describe, expect, it } from "vitest"

import {
  adSetEditProblem,
  adSetEditRows,
  editAdSets,
  parseAdSetEditArgs,
} from "@/integrations/meta_ads/lib/ad-set-edits"
import { metaAdsUpdateAdSetsPresenter } from "@/integrations/meta_ads/presenters/update-ad-sets"
import { APPROVE_DISABLED, props, render } from "./presenter-harness"

function adSet(id: string, label: string) {
  return {
    version: 1,
    entity_kind: "meta_ads_ad_set",
    label,
    account_id: "111",
    campaign_id: "1",
    adset_id: id,
  }
}

const spring = { ad_set: adSet("8", "Spring UK"), end_date: "2026-05-31", bid_amount: "12" }
const summer = { ad_set: adSet("7", "Summer IE"), max_daily_spend: "remove" }
const checks = {
  "8": {
    currency: "GBP",
    before: { end_date: "2026-05-15", bid_amount: "15" },
    requested: { end_date: "2026-05-31", bid_amount: "12" },
    problems: [],
    notes: ["This restarts learning. Results may swing for a few days."],
  },
  "7": {
    currency: "GBP",
    before: { max_daily_spend: "40" },
    requested: { max_daily_spend: null },
    problems: ["Daily spend limits need a campaign daily budget."],
    notes: [],
  },
}

describe("Meta Ads ad set edits", () => {
  it("blocks on Meta's problem only while the card still shows the values it was found for", () => {
    const proposed = parseAdSetEditArgs({ changes: [spring, summer], _checks: checks })
    if (!proposed) throw new Error("expected proposed edits")
    expect(adSetEditProblem(proposed)).toContain("Meta won't accept")

    const edited = editAdSets(adSetEditRows(proposed, proposed), "7", {
      key: "max_daily_spend",
      value: "30",
    })
    expect(adSetEditProblem(parseAdSetEditArgs({ changes: edited, _checks: checks }))).toBeNull()
  })

  it("drops an ad set and brings it back with the values it was proposed with", () => {
    const proposed = parseAdSetEditArgs({ changes: [spring, summer] })
    if (!proposed) throw new Error("expected proposed edits")
    const dropped = editAdSets(adSetEditRows(proposed, proposed), "7", { included: false })
    expect(dropped).toEqual([spring])

    const current = parseAdSetEditArgs({ changes: dropped })
    if (!current) throw new Error("expected current edits")
    expect(editAdSets(adSetEditRows(proposed, current), "7", { included: true })).toEqual([
      spring,
      summer,
    ])
  })
})

describe("Meta Ads update ad sets presenter", () => {
  it("shows each ad set's settings now and after, with its impact notes", () => {
    const html = render(approval({ changes: [spring], _checks: { "8": checks["8"] } }))

    expect(html).toContain("Spring UK")
    expect(html).toContain("15 May 2026")
    expect(html).toContain("This restarts learning.")
    expect(html).not.toMatch(APPROVE_DISABLED)
  })

  it("shows the value Meta reads back for each setting", () => {
    const html = render(
      metaAdsUpdateAdSetsPresenter.render(
        props({
          id: "r1",
          kind: "result",
          name: "meta_ads_update_ad_sets",
          status: "completed",
          args: { changes: [spring] },
          result: {
            results: [
              {
                provider_key: "meta_ads",
                external_id: "111",
                display_name: "Example ad account",
                status: "success",
                data: {
                  account_id: "111",
                  currency: "GBP",
                  ad_sets: [
                    {
                      adset_id: "8",
                      name: "Spring UK",
                      changes: [
                        {
                          setting: "end_date",
                          before: "2026-05-15",
                          requested: "2026-05-31",
                          after: "2026-05-31",
                        },
                      ],
                      outcome: "updated",
                      error_code: null,
                      message: null,
                    },
                  ],
                },
              },
            ],
          },
        })
      )
    )

    expect(html).toContain("31 May 2026")
    expect(html).toContain("Updated")
  })
})

function approval(args: Record<string, unknown>) {
  return metaAdsUpdateAdSetsPresenter.render(
    props(
      {
        id: "a1",
        kind: "approval",
        name: "meta_ads_update_ad_sets",
        status: "awaiting_approval",
        args,
      },
      true
    )
  )
}
