// apps/web/tests/integrations/meta-ads/update-campaigns.test.ts

import { describe, expect, it } from "vitest"

import {
  campaignEditProblem,
  campaignEditRows,
  editCampaigns,
  parseCampaignEditArgs,
} from "@/integrations/meta_ads/lib/campaign-edits"
import { metaAdsUpdateCampaignsPresenter } from "@/integrations/meta_ads/presenters/update-campaigns"
import { APPROVE_DISABLED, props, render } from "./presenter-harness"

function campaign(id: string, label: string) {
  return {
    version: 1,
    entity_kind: "meta_ads_campaign",
    label,
    account_id: "111",
    campaign_id: id,
  }
}

function bid(id: string, amount: string) {
  return {
    ad_set: {
      version: 1,
      entity_kind: "meta_ads_ad_set",
      label: `Ad set ${id}`,
      account_id: "111",
      campaign_id: "5",
      adset_id: id,
    },
    bid_amount: amount,
  }
}

const costGoal = {
  campaign: campaign("5", "Autumn sale"),
  bid_strategy: "cost_per_result_goal",
  ad_set_bids: [bid("51", "12"), bid("52", "9.50")],
}
const checks = {
  "5": {
    currency: "GBP",
    before: { bid_strategy: "highest_volume", ad_set_bids: '{"51":null,"52":null}' },
    requested: { bid_strategy: "cost_per_result_goal", ad_set_bids: '{"51":"12","52":"9.5"}' },
    problems: ["Meta says the target cost is too low."],
    warnings: ["This restarts learning in every ad set in the campaign."],
    notes: [],
    ad_sets: [
      { id: "51", name: "Prospecting", bid: null },
      { id: "52", name: "Retargeting", bid: null },
    ],
  },
}

describe("Meta Ads campaign edits", () => {
  it("blocks on Meta's problem until a bid changes, comparing bids as amounts", () => {
    const proposed = parseCampaignEditArgs({ changes: [costGoal], _checks: checks })
    if (!proposed) throw new Error("expected proposed edits")
    expect(campaignEditProblem(proposed)).toContain("Meta won't accept")

    const edited = editCampaigns(campaignEditRows(proposed, proposed), "5", {
      bid: "52",
      value: "11",
    })
    expect(campaignEditProblem(parseCampaignEditArgs({ changes: edited, _checks: checks }))).toBe(
      null
    )
  })

  it("drops the ad set bids for highest volume and restores them for a cost goal", () => {
    const proposed = parseCampaignEditArgs({ changes: [costGoal] })
    if (!proposed) throw new Error("expected proposed edits")
    const volume = editCampaigns(campaignEditRows(proposed, proposed), "5", {
      key: "bid_strategy",
      value: "highest_volume",
    })
    expect(volume).toEqual([{ campaign: costGoal.campaign, bid_strategy: "highest_volume" }])

    const current = parseCampaignEditArgs({ changes: volume })
    if (!current) throw new Error("expected current edits")
    expect(
      editCampaigns(campaignEditRows(proposed, current), "5", {
        key: "bid_strategy",
        value: "bid_cap",
      })
    ).toEqual([{ ...costGoal, bid_strategy: "bid_cap" }])
  })
})

describe("Meta Ads update campaigns presenter", () => {
  it("shows each ad set's bid with its current one, and blocks a change Meta refused", () => {
    const html = render(
      metaAdsUpdateCampaignsPresenter.render(
        props(
          {
            id: "a1",
            kind: "approval",
            name: "meta_ads_update_campaigns",
            status: "awaiting_approval",
            args: { changes: [costGoal], _checks: checks },
          },
          true
        )
      )
    )

    expect(html).toContain("Retargeting")
    expect(html).toMatch(APPROVE_DISABLED)
  })
})
