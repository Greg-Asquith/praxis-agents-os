// apps/web/tests/integrations/meta-ads/update-ads.test.ts

import { describe, expect, it } from "vitest"

import {
  adEditProblem,
  adEditRows,
  editAds,
  parseAdEditArgs,
} from "@/integrations/meta_ads/lib/ad-edits"
import { metaAdsUpdateAdsPresenter } from "@/integrations/meta_ads/presenters/update-ads"
import { APPROVE_DISABLED, props, render } from "./presenter-harness"

function ad(id: string, label: string) {
  return {
    version: 1,
    entity_kind: "meta_ads_ad",
    label,
    account_id: "111",
    campaign_id: "1",
    adset_id: "2",
    ad_id: id,
  }
}

const video = { ad: ad("8", "Sale video"), name: "UK | Sale | Video", end_at: "2026-11-29T23:59" }
const checks = {
  "8": {
    time_zone: "Europe/London",
    before: { name: "Sale video", end_at: null },
    requested: { name: "UK | Sale | Video", end_at: "2026-11-29T23:59" },
    problems: ["Set end_at to 28 Nov 2026, 23:59 or earlier, when the ad set ends."],
    ad_set_schedule: { start_at: "2026-11-01T00:00", end_at: "2026-11-28T23:59" },
    unavailable: false,
  },
}

describe("Meta Ads ad edits", () => {
  it("blocks on Meta's problem only while the card still shows the values it was found for", () => {
    const proposed = parseAdEditArgs({ changes: [video], _checks: checks })
    if (!proposed) throw new Error("expected proposed edits")
    expect(adEditProblem(proposed)).toContain("Meta won't accept")

    const edited = editAds(adEditRows(proposed, proposed), "8", {
      key: "end_at",
      value: "2026-11-28T20:00",
    })
    expect(adEditProblem(parseAdEditArgs({ changes: edited, _checks: checks }))).toBeNull()
  })
})

describe("Meta Ads update ads presenter", () => {
  it("shows each ad's new values with its current ones", () => {
    const html = render(
      metaAdsUpdateAdsPresenter.render(
        props(
          {
            id: "a1",
            kind: "approval",
            name: "meta_ads_update_ads",
            status: "awaiting_approval",
            args: {
              changes: [video],
              _checks: { "8": { ...checks["8"], problems: [] } },
            },
          },
          true
        )
      )
    )

    expect(html).toContain("Sale video")
    expect(html).toContain("Follows the ad set")
    expect(html).toContain("28 Nov 2026")
    expect(html).not.toMatch(APPROVE_DISABLED)
  })
})
