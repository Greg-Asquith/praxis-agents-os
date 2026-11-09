// apps/web/tests/integrations/google-ads/update-campaigns.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  campaignCounts,
  campaignRows,
  campaignsApproveLabel,
  campaignsBlock,
  editedChanges,
  parseUpdateCampaignsArgs,
  restoredChanges,
  type UpdateCampaignsArgs,
} from "@/integrations/google_ads/lib/update-campaigns"
import { googleAdsUpdateCampaignsPresenter } from "@/integrations/google_ads/presenters/update-campaigns"

const CUSTOMER = "1234567890"
const key = (id: string) => `customers/${CUSTOMER}/campaigns/${id}`

function campaign(id: string) {
  return { customer_id: CUSTOMER, campaign_id: id, label: `Campaign ${id}` }
}

function check(over: Record<string, unknown> = {}) {
  return {
    unavailable: false,
    name: "Trail",
    current: { name: "Trail", end_date: "2026-12-31", search_partners: true },
    requested: { end_date: null, search_partners: false },
    problem: null,
    problems: {},
    ...over,
  }
}

function raw(over: Record<string, unknown> = {}) {
  return {
    changes: [{ campaign: campaign("10"), end_date: "none", networks: { search_partners: false } }],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: { [key("10")]: check() },
    ...over,
  }
}

function parsed(value: unknown = raw()): UpdateCampaignsArgs {
  const args = parseUpdateCampaignsArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

function edited(changes: unknown[]): UpdateCampaignsArgs {
  return parsed({ ...raw(), changes })
}

describe("approval", () => {
  it("holds a problem to the value Google checked, and an edit waits for a new check", () => {
    const checked = parsed(
      raw({ _checks: { [key("10")]: check({ problems: { end_date: "Choose a later date." } }) } })
    )
    expect(campaignsBlock(checked, checked)).toBe("Fix or cancel 1 change to continue.")

    const ids = new Set([`${key("10")}|end_date`])
    const next = edited(editedChanges(checked, ids, () => "2027-01-31"))

    expect(campaignRows(next, checked).map((row) => row.problem)).toEqual([null, null])
    expect(campaignsBlock(next, checked)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )
  })

  it("takes a campaign out when every setting is cancelled, and Undo brings it back", () => {
    const args = parsed()
    const ids = new Set([`${key("10")}|end_date`, `${key("10")}|search_partners`])

    expect(editedChanges(args, ids, () => undefined)).toEqual([])

    const restored = restoredChanges(edited([]), [
      { campaign: campaign("10"), key: key("10"), setting: "end_date", value: null },
    ])
    expect(restored).toEqual([{ campaign: campaign("10"), end_date: "none" }])
  })

  it("doesn't count a setting already at its value, and names a sole change on the button", () => {
    const args = parsed(
      raw({ changes: [{ campaign: campaign("10"), networks: { search_partners: true } }] })
    )
    expect(campaignCounts(campaignRows(args, args)).apply).toBe(0)

    const removal = parsed(raw({ changes: [{ campaign: campaign("10"), end_date: "none" }] }))
    expect(campaignsApproveLabel(removal)).toBe("Remove End Date")
  })
})

describe("presenters", () => {
  const html = (node: ReactNode) =>
    renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        createElement("div", null, node)
      )
    )
  const props = (activity: ToolActivity, withApproval = false) => ({
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
    providerKey: "google_ads",
  })

  it("renders the approval and the result", () => {
    const approval = html(
      googleAdsUpdateCampaignsPresenter.render(
        props(
          {
            id: "campaigns-1",
            kind: "approval",
            name: "google_ads_update_campaigns",
            status: "awaiting_approval",
            args: raw(),
          },
          true
        )
      )
    )
    expect(approval).toContain("31 Dec 2026")

    const result = html(
      googleAdsUpdateCampaignsPresenter.render(
        props({
          id: "campaigns-2",
          kind: "result",
          name: "google_ads_update_campaigns",
          status: "completed",
          args: raw(),
          result: {
            results: [
              {
                provider_key: "google_ads",
                display_name: "Northwind",
                external_id: CUSTOMER,
                status: "success",
                data: {
                  account_id: CUSTOMER,
                  campaigns: [
                    {
                      resource_name: key("10"),
                      campaign_id: "10",
                      name: "Trail",
                      read_back: true,
                      settings: [
                        {
                          setting: "end_date",
                          before: "2026-12-31",
                          requested: null,
                          after: null,
                          outcome: "updated",
                        },
                      ],
                    },
                  ],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("No end date")
  })
})
