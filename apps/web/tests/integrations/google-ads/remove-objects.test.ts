// apps/web/tests/integrations/google-ads/remove-objects.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  editedItems,
  parseRemoveObjectsArgs,
  removalApproveLabel,
  removalBannerDetail,
  removalBlock,
  removalCounts,
  removalRows,
  type RemoveObjectsArgs,
} from "@/integrations/google_ads/lib/remove-objects"
import { googleAdsRemoveObjectsPresenter } from "@/integrations/google_ads/presenters/remove-objects"

const CUSTOMER = "1234567890"
const AD_GROUP = `customers/${CUSTOMER}/adGroups/20`
const LABEL = `customers/${CUSTOMER}/labels/8`
const USED_BUDGET = `customers/${CUSTOMER}/campaignBudgets/7`
const IN_USE = "Still funds Hiking Boots. Move it to another budget first."

function raw(over: Record<string, unknown> = {}) {
  return {
    items: [
      {
        kind: "ad_group",
        ad_group: { customer_id: CUSTOMER, campaign_id: "10", ad_group_id: "20", label: "Sandals" },
      },
      { kind: "label", label: { customer_id: CUSTOMER, label_id: "8", label: "Summer" } },
      { kind: "budget", budget: { customer_id: CUSTOMER, budget_id: "7", label: "Brand" } },
    ],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: {
      [AD_GROUP]: {
        unavailable: false,
        name: "Summer Sandals",
        status: "ENABLED",
        campaign_name: "Trail Running Shoes",
        dependants: { ads: 6, keywords: 92, truncated: false },
        problem: null,
      },
      [LABEL]: {
        unavailable: false,
        name: "Summer",
        status: "ENABLED",
        dependants: { campaigns: 3, truncated: false },
        problem: null,
      },
      [USED_BUDGET]: {
        unavailable: false,
        name: "Brand Shared",
        status: "ENABLED",
        dependants: { campaigns: 1, truncated: false },
        problem: IN_USE,
      },
    },
    ...over,
  }
}

function parsed(value: unknown = raw()): RemoveObjectsArgs {
  const args = parseRemoveObjectsArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

describe("approval", () => {
  it("blocks on a budget still in use until it is cancelled, and counts what goes with the rest", () => {
    const proposed = parsed()
    expect(removalBlock(proposed)).toBe("Cancel 1 change that can't go ahead to continue.")

    const rows = removalRows(proposed, proposed)
    const edited = parsed(raw({ items: editedItems(rows, new Set([USED_BUDGET]), true) }))
    const counts = removalCounts(removalRows(proposed, edited))

    expect(removalBlock(edited)).toBeNull()
    expect(removalApproveLabel(counts)).toBe("Remove 2 Items")
    // A label's campaigns stay; only the ad group's ads and keywords go with it.
    expect(removalBannerDetail(counts)).toBe(
      "2 items · also removes 6 ads, 92 keywords inside them"
    )
  })
})

describe("presenters", () => {
  const html = (node: ReactNode) => renderToStaticMarkup(createElement("div", null, node))
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
      googleAdsRemoveObjectsPresenter.render(
        props(
          {
            id: "remove-1",
            kind: "approval",
            name: "google_ads_remove_objects",
            status: "awaiting_approval",
            args: raw(),
          },
          true
        )
      )
    )
    expect(approval).toContain(IN_USE)

    const result = html(
      googleAdsRemoveObjectsPresenter.render(
        props({
          id: "remove-2",
          kind: "result",
          name: "google_ads_remove_objects",
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
                  objects: [
                    {
                      kind: "ad_group",
                      resource_name: AD_GROUP,
                      name: "Summer Sandals",
                      campaign_name: "Trail Running Shoes",
                      dependants: { ads: 6, keywords: 92, truncated: false },
                      outcome: "removed",
                    },
                  ],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("92 keywords")
  })
})
