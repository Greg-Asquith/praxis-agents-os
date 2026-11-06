// apps/web/tests/integrations/meta-ads/update-ads.test.ts

import { describe, expect, it } from "vitest"

import { creativeChanges, parseCreativeCheck } from "@/integrations/meta_ads/lib/ad-creative-edits"
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

const image = (hash: string) => ({
  version: 1,
  entity_kind: "meta_ads_media",
  label: "Current image",
  account_id: "111",
  media_type: "image",
  image_hash: hash,
})
const live = {
  format: "image",
  primary_text: "Everything half price.",
  headline: "Weekend sael",
  description: "Ends Sunday",
  link: "https://example.com/sale",
  call_to_action: "SHOP_NOW",
  media: image("a1"),
}
const headlineFix = { ad: ad("9", "Sale image"), creative: { headline: "Weekend sale" } }
const creativeCheck = {
  time_zone: "Europe/London",
  before: { name: "Sale image", creative_id: "4001" },
  requested: {},
  requested_creative: { headline: "Weekend sale" },
  problems: [],
  ad_set_schedule: null,
  creative: {
    content: live,
    ad_set: { adset_id: "2", label: "UK prospecting", objective: "OUTCOME_SALES" },
    page_id: "77",
    page_name: "Example Shop",
    changed: ["headline"],
    automatic_changes: [],
    buttons: ["LEARN_MORE", "SHOP_NOW"],
    notes: ["This restarts learning for the ad set."],
  },
  unavailable: false,
}

describe("Meta Ads creative edits", () => {
  it("sends only the parts that differ from the live creative, and none for a removed one", () => {
    const check = parseCreativeCheck(creativeCheck.creative)
    if (!check) throw new Error("expected a creative check")
    // The same image under another label is unchanged; the headline went back to the live one.
    const edited = { ...live, headline: "Weekend sael", description: null, media: image("a1") }

    expect(creativeChanges(check, edited, {})).toEqual({ description: "none" })
    expect(
      creativeChanges(check, { ...live, media: image("b2") }, { automatic_changes: [] })
    ).toEqual({ media: image("b2"), automatic_changes: [] })
  })
})

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
  it("shows a new creative before and after, beside the other ads", () => {
    const html = render(
      metaAdsUpdateAdsPresenter.render(
        props(
          {
            id: "a1",
            kind: "approval",
            name: "meta_ads_update_ads",
            status: "awaiting_approval",
            args: {
              changes: [headlineFix, video],
              _checks: { "8": { ...checks["8"], problems: [] }, "9": creativeCheck },
              _automatic_change_catalogue: [],
            },
          },
          true
        )
      )
    )

    expect(html).toContain("Sale video")
    expect(html).toContain("After Approval")
    expect(html).not.toMatch(APPROVE_DISABLED)
  })
})
