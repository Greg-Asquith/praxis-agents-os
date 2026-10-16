// apps/web/tests/integrations/meta-ads/launch-campaign.test.ts

import { describe, expect, it } from "vitest"

import { setAdSets } from "@/integrations/meta_ads/lib/create-ads-edits"
import {
  adSetEdit,
  adsEdit,
  parseLaunchArgs,
  spendLine,
  type LaunchArgs,
} from "@/integrations/meta_ads/lib/launch-model"
import { metaAdsLaunchCampaignPresenter } from "@/integrations/meta_ads/presenters/launch-campaign"
import { APPROVE_DISABLED, props, render } from "./presenter-harness"

const page = {
  version: 1,
  entity_kind: "meta_ads_page",
  account_id: "123",
  page_id: "11",
  label: "Acme",
}
const image = {
  version: 1,
  entity_kind: "meta_ads_media",
  account_id: "123",
  media_type: "image",
  image_hash: "abc",
  label: "hero.jpg",
}
const eu = { applies: false, default_payer: null, default_beneficiary: null }

function adSet(key: string, name: string, budget: Record<string, unknown> | null) {
  return {
    key,
    name,
    goal: "link_clicks",
    page,
    budget,
    targeting: { locations: [{ kind: "country", key: "GB", name: "United Kingdom" }] },
  }
}

function ad(name: string, keys: string[]) {
  return {
    name,
    ad_set_keys: keys,
    format: "image",
    primary_text: "Spring sale on now",
    headline: "20% off",
    media: image,
  }
}

function display(overrides: Record<string, unknown> = {}) {
  return {
    campaign: {
      name: "Spring Sale",
      objective: "traffic",
      budget: { mode: "ad_set", share_between_ad_sets: false },
    },
    ad_sets: [
      adSet("uk", "UK prospecting", { kind: "daily", amount: "45" }),
      adSet("ie", "Ireland prospecting", { kind: "daily", amount: "75" }),
    ],
    ads: [ad("Spring", ["uk", "ie"])],
    page,
    link: "https://example.com/spring",
    go_live: false,
    _account: { account_id: "123", resource_id: "r" },
    _account_name: "Acme UK",
    _currency: "GBP",
    _timezone: "Europe/London",
    _minimum: "5",
    _minimum_spend_limit: null,
    _ad_set_accounts: {
      uk: { minimum: "1", minimum_goal: "link_clicks", eu },
      ie: { minimum: "1", minimum_goal: "link_clicks", eu },
    },
    _media: { "image:abc": { ...image, width: 1080, height: 1080 } },
    _posts: {},
    _files: [],
    _automatic_change_catalogue: [],
    _buttons: { website: ["LEARN_MORE"], app: ["INSTALL_MOBILE_APP"] },
    ...overrides,
  }
}

function parsed(overrides: Record<string, unknown> = {}): LaunchArgs {
  const args = parseLaunchArgs(display(overrides))
  if (!args) throw new Error("fixture didn't parse")
  return args
}

function activity(kind: "approval" | "result", args: Record<string, unknown>, result?: unknown) {
  return {
    id: "l1",
    kind,
    name: "meta_ads_launch_campaign",
    status: kind === "approval" ? ("awaiting_approval" as const) : ("completed" as const),
    args,
    ...(result === undefined ? {} : { result }),
  }
}

function launchedObject(extra: Record<string, unknown>) {
  return { recovered: false, verified: true, error_code: null, message: null, ...extra }
}

describe("Meta Ads launch model", () => {
  it("adds up ad set budgets, and uses the campaign's own budget when it has one", () => {
    expect(spendLine(parsed())).toMatch(/120.*a day in total.*75%.*7 times/)

    const campaignBudget = {
      campaign: {
        name: "Spring Sale",
        objective: "traffic",
        budget: { mode: "campaign_daily", amount: "90" },
      },
      ad_sets: [adSet("uk", "UK prospecting", null), adSet("ie", "Ireland prospecting", null)],
    }
    expect(spendLine(parsed(campaignBudget))).toMatch(/90.*a day in total/)
  })

  it("edits one ad set, and writes ads back with ad set keys and no status", () => {
    const args = parsed()
    const edited = adSetEdit(args, "ie", { name: "Ireland retargeting" })
    expect(edited).toEqual({
      ad_sets: [args.adSets[0]?.raw, { ...args.adSets[1]?.raw, name: "Ireland retargeting" }],
    })

    const moved = adsEdit(setAdSets(args.ads, 0, [{ adset_id: "ie" }]))
    expect(moved).toEqual({ ads: [{ ...ad("Spring", []), ad_set_keys: ["ie"] }] })
  })

  it("renders the approval and blocks an ad set with no ads", () => {
    const html = render(
      metaAdsLaunchCampaignPresenter.render(props(activity("approval", display()), true))
    )
    expect(html).not.toMatch(APPROVE_DISABLED)

    const withoutAds = display({ ads: [ad("Spring", ["uk"])] })
    expect(
      render(metaAdsLaunchCampaignPresenter.render(props(activity("approval", withoutAds), true)))
    ).toMatch(APPROVE_DISABLED)
  })

  it("shows what was built and what failed when the launch is partial", () => {
    const data = {
      account_id: "123",
      currency: "GBP",
      state: "partial",
      message: "Partly built, and nothing is on.",
      go_live: true,
      campaign: launchedObject({
        name: "Spring Sale",
        objective: "traffic",
        outcome: "created",
        campaign_id: "9",
        effective_status: "PAUSED",
        campaign: null,
      }),
      campaign_turned_on: "not_turned_on",
      ad_sets: [
        launchedObject({
          key: "uk",
          name: "UK prospecting",
          campaign_id: "9",
          goal: "link_clicks",
          outcome: "failed",
          adset_id: null,
          effective_status: null,
          ad_set: null,
          turned_on: "not_turned_on",
          message: "Budget too low.",
        }),
      ],
      ads: [
        launchedObject({
          ad_set_key: "uk",
          adset_id: null,
          design_index: 0,
          name: "Spring",
          adset_name: "UK prospecting",
          format: "image",
          requested_status: "active",
          outcome: "failed",
          ad_id: null,
          creative_id: null,
          effective_status: null,
          review: "unknown",
          review_reasons: [],
          unexpected_changes: [],
          preview_url: null,
        }),
      ],
      uploads: [],
      automatic_changes: [],
      created_off_for_ai: false,
    }
    const entry = {
      provider_key: "meta_ads",
      external_id: "123",
      display_name: "Acme UK",
      status: "success",
      error_code: null,
      error_message: null,
      data,
    }

    const html = render(
      metaAdsLaunchCampaignPresenter.render(
        props(activity("result", display(), { results: [entry] }))
      )
    )
    expect(html).toContain("Budget too low.")
    expect(html).toContain('href="https://adsmanager.facebook.com/adsmanager/manage/campaigns')
  })
})
