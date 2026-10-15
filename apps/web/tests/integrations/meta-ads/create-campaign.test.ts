// apps/web/tests/integrations/meta-ads/create-campaign.test.ts

import { createElement, type ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import { metaAdsCreateCampaignPresenter } from "@/integrations/meta_ads/presenters/create-campaign"

const APPROVE_DISABLED = /<button[^>]*\sdisabled=""[^>]*>Approve/

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
  it("states the campaign in sentences and blocks a budget under the account minimum", () => {
    expect(render(approval(display()))).not.toMatch(APPROVE_DISABLED)
    expect(render(approval(display({ _minimum: "200" })))).toMatch(APPROVE_DISABLED)
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

function props(activity: ToolActivity, withApproval = false) {
  return {
    activity,
    ...(withApproval
      ? {
          approvalDecision: {
            decision: { decision: "pending" as const, edits: {}, message: "" as const },
            error: null,
            onDecisionChange: vi.fn(),
            onRetry: vi.fn(),
            pendingCount: 1,
            submitting: false,
          },
        }
      : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "meta_ads",
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement("div", null, node)
    )
  )
}
