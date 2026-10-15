// apps/web/tests/integrations/meta-ads/create-campaign.test.ts

import { describe, expect, it } from "vitest"

import {
  campaignBudgetValue,
  createCampaignProblem,
  parseCreateCampaignArgs,
} from "@/integrations/meta_ads/lib/create-campaign"
import { editFields } from "@/integrations/meta_ads/lib/create-summary"
import { metaAdsCreateCampaignPresenter } from "@/integrations/meta_ads/presenters/create-campaign"
import { vi } from "vitest"

import { APPROVE_DISABLED, props, render } from "./presenter-harness"

function display(extra: Record<string, unknown> = {}) {
  return {
    name: "Spring launch",
    objective: "sales",
    budget: { mode: "campaign_daily", amount: "150" },
    bid_strategy: "highest_volume",
    _account: { account_id: "123", resource_id: "r" },
    _account_name: "Acme UK",
    _currency: "GBP",
    _timezone: "Europe/London",
    _minimum: "1",
    _minimum_spend_limit: null,
    ...extra,
  }
}

describe("Meta Ads create campaign presenter", () => {
  it("blocks a budget under the account minimum", () => {
    expect(render(approval(display()))).not.toMatch(APPROVE_DISABLED)
    expect(render(approval(display({ _minimum: "200" })))).toMatch(APPROVE_DISABLED)
  })

  it("sends only the budget fields the chosen mode takes", () => {
    const budget = { mode: "ad_set" as const, amount: "150", shareBetweenAdSets: null }
    expect(campaignBudgetValue(budget)).toEqual({
      mode: "ad_set",
      share_between_ad_sets: false,
    })
    expect(
      campaignBudgetValue({ mode: "campaign_daily", amount: "150", shareBetweenAdSets: true })
    ).toEqual({ mode: "campaign_daily", amount: "150" })
  })

  it("blocks a cleared amount and a category with no country", () => {
    const problem = (extra: Record<string, unknown>) =>
      createCampaignProblem(parseCreateCampaignArgs(display(extra)))
    expect(problem({})).toBeNull()
    expect(problem({ budget: { mode: "campaign_daily" } })).toMatch(/budget amount/)
    expect(problem({ special_ad_categories: [{ category: "housing", countries: [] }] })).toMatch(
      /country/
    )
  })

  it("applies several edits in one decision change", () => {
    const onDecisionChange = vi.fn()
    const controls = {
      decision: { decision: "pending" as const, edits: { name: "Kept" }, message: "" as const },
      error: null,
      onDecisionChange,
      onRetry: vi.fn(),
      pendingCount: 1,
      submitting: false,
    }
    editFields(controls, false, { objective: "traffic", bid_strategy: "highest_volume" })
    editFields(controls, true, { name: "Ignored" })

    expect(onDecisionChange).toHaveBeenCalledTimes(1)
    expect(onDecisionChange).toHaveBeenCalledWith({
      decision: "pending",
      edits: { name: "Kept", objective: "traffic", bid_strategy: "highest_volume" },
      message: "",
    })
  })

  it("links a created campaign to Ads Manager", () => {
    const html = render(
      metaAdsCreateCampaignPresenter.render(
        props({
          id: "r1",
          kind: "result",
          name: "meta_ads_create_campaign",
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
                  campaign: {
                    name: "Spring launch",
                    objective: "sales",
                    outcome: "created",
                    recovered: false,
                    verified: true,
                    campaign_id: "901",
                    effective_status: "PAUSED",
                    campaign: null,
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

    expect(html).toContain("selected_campaign_ids=901")
  })
})

function approval(args: Record<string, unknown>) {
  return metaAdsCreateCampaignPresenter.render(
    props(
      {
        id: "a1",
        kind: "approval",
        name: "meta_ads_create_campaign",
        status: "awaiting_approval",
        args,
      },
      true
    )
  )
}
