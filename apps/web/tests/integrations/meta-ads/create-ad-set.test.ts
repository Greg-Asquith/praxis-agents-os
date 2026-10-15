// apps/web/tests/integrations/meta-ads/create-ad-set.test.ts

import { describe, expect, it } from "vitest"

import {
  createAdSetProblem,
  goalEdits,
  parseCreateAdSetArgs,
} from "@/integrations/meta_ads/lib/create-ad-set"
import {
  addInterest,
  addLocation,
  removeDetailed,
} from "@/integrations/meta_ads/lib/targeting-edit"
import { metaAdsCreateAdSetPresenter } from "@/integrations/meta_ads/presenters/create-ad-set"
import { APPROVE_DISABLED, props, render } from "./presenter-harness"

function display(extra: Record<string, unknown> = {}) {
  return {
    campaign: {
      entity_kind: "meta_ads_campaign",
      account_id: "123",
      campaign_id: "9",
      label: "Spring Sale",
      objective: "OUTCOME_SALES",
    },
    name: "UK runners",
    goal: "website_conversions",
    targeting: { locations: [{ kind: "country", key: "GB", name: "United Kingdom" }] },
    pixel: {
      entity_kind: "meta_ads_pixel",
      account_id: "123",
      pixel_id: "77",
      label: "Shop Pixel",
    },
    conversion_event: "PURCHASE",
    budget: { kind: "daily", amount: "40" },
    _account: { account_id: "123", resource_id: "r" },
    _account_name: "Acme UK",
    _currency: "GBP",
    _timezone: "Europe/London",
    _minimum: "5",
    _eu: { applies: false, default_payer: null, default_beneficiary: null },
    ...extra,
  }
}

describe("Meta Ads create ad set presenter", () => {
  it("blocks missing EU names or a custom conversion from another pixel", () => {
    expect(render(approval(display()))).not.toMatch(APPROVE_DISABLED)

    const france = display({
      targeting: { locations: [{ kind: "country", key: "FR", name: "France" }] },
      _eu: { applies: true, default_payer: null, default_beneficiary: null },
    })
    expect(render(approval(france))).toMatch(APPROVE_DISABLED)

    const otherPixel = display({
      conversion_event: null,
      custom_conversion_id: "300",
      _custom_conversion: { name: "Big basket", pixel_id: "99" },
    })
    expect(render(approval(otherPixel))).toMatch(APPROVE_DISABLED)
  })

  it("drops what the new goal doesn't use and ignores a stale minimum", () => {
    const args = parseCreateAdSetArgs(
      display({ _minimum: "50", _minimum_goal: "website_conversions" })
    )
    if (!args) throw new Error("expected args")
    expect(createAdSetProblem(args)).toMatch(/minimum daily budget/)
    const edited = parseCreateAdSetArgs(
      display({ _minimum: "50", _minimum_goal: "website_conversions", goal: "link_clicks" })
    )
    expect(createAdSetProblem(edited)).toBeNull()
    expect(goalEdits(args, "link_clicks")).toEqual({
      goal: "link_clicks",
      pixel: null,
      conversion_event: null,
    })
  })

  it("blocks Advantage+ audience with a maximum age, and manual placements with no place", () => {
    const problem = (extra: Record<string, unknown>) =>
      createAdSetProblem(parseCreateAdSetArgs(display(extra)))
    const targeting = { locations: [{ kind: "country", key: "GB", name: "United Kingdom" }] }
    expect(problem({ targeting: { ...targeting, age_max: 54 } })).toMatch(/Advantage\+/)
    expect(
      problem({ targeting: { ...targeting, age_max: 54, advantage_audience: false } })
    ).toBeNull()
    expect(problem({ placements: { mode: "manual", positions: [] } })).toMatch(/at least one place/)
  })

  it("edits targeting lists without duplicates or empty groups", () => {
    const place = { entity_kind: "x", kind: "city", key: "1", name: "Leeds", country_code: "GB" }
    const added = addLocation({ locations: [] }, "locations", place)
    expect(added).toEqual({
      locations: [{ kind: "city", key: "1", name: "Leeds", country_code: "GB" }],
    })
    expect(addLocation(added, "locations", place)).toBe(added)

    const interest = { kind: "interest", key: "6", name: "Running", label: "Running" }
    const withInterest = addInterest({}, interest)
    expect(withInterest).toEqual({ detailed: [[{ kind: "interest", key: "6", name: "Running" }]] })
    expect(addInterest(withInterest, interest)).toBe(withInterest)
    expect(removeDetailed(withInterest, 0, 0)).toEqual({ detailed: [] })
  })

  it("links a created ad set to Ads Manager", () => {
    const html = render(
      metaAdsCreateAdSetPresenter.render(
        props({
          id: "r1",
          kind: "result",
          name: "meta_ads_create_ad_set",
          status: "completed",
          args: display(),
          result: {
            results: [
              {
                provider_key: "meta_ads",
                external_id: "123",
                display_name: "Acme UK",
                status: "success",
                error_code: null,
                error_message: null,
                data: {
                  account_id: "123",
                  currency: "GBP",
                  ad_set: {
                    name: "UK runners",
                    campaign_id: "9",
                    goal: "website_conversions",
                    outcome: "created",
                    recovered: false,
                    verified: true,
                    adset_id: "801",
                    effective_status: "PAUSED",
                    ad_set: null,
                    eu_transparency: "not_needed",
                    error_code: null,
                    message: null,
                  },
                },
              },
            ],
          },
        })
      )
    )

    expect(html).toContain("selected_adset_ids=801")
  })
})

function approval(args: Record<string, unknown>) {
  return metaAdsCreateAdSetPresenter.render(
    props(
      {
        id: "a1",
        kind: "approval",
        name: "meta_ads_create_ad_set",
        status: "awaiting_approval",
        args,
      },
      true
    )
  )
}
