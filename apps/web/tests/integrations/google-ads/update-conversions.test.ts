// apps/web/tests/integrations/google-ads/update-conversions.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  conversionRows,
  conversionsBlock,
  editedConversions,
  parseUpdateConversionsArgs,
  restoredConversions,
  type UpdateConversionsArgs,
} from "@/integrations/google_ads/lib/update-conversions"
import { googleAdsUpdateConversionsPresenter } from "@/integrations/google_ads/presenters/update-conversions"

const CUSTOMER = "1234567890"
const ACTION = `customers/${CUSTOMER}/conversionActions/7`
const GOAL = `customers/${CUSTOMER}/customerConversionGoals/PHONE_CALL_LEAD~CALL_FROM_ADS`

const action = {
  customer_id: CUSTOMER,
  conversion_action_id: "7",
  label: "Newsletter Sign-Up",
}
const goal = {
  customer_id: CUSTOMER,
  category: "PHONE_CALL_LEAD",
  origin: "CALL_FROM_ADS",
  label: "Phone call lead from call from ads",
}

function raw(over: Record<string, unknown> = {}) {
  return {
    changes: [{ conversion_action: action, primary: false, default_value: "10" }],
    account_goals: [{ goal, biddable: false }],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: {
      [ACTION]: {
        unavailable: false,
        name: "Newsletter Sign-Up",
        conversions: 1284,
        current: { primary: true, default_value: "1", currency: "GBP" },
        requested: { primary: false, default_value: "10" },
        problem: null,
      },
      [GOAL]: {
        unavailable: false,
        conversions: 96,
        current: { biddable: true },
        requested: { biddable: false },
        problem: null,
      },
    },
    ...over,
  }
}

function parsed(value: unknown = raw()): UpdateConversionsArgs {
  const args = parseUpdateConversionsArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

describe("approval", () => {
  it("cancels an account goal out of its own field, and Undo brings it back", () => {
    const args = parsed()
    expect(conversionsBlock(args, args)).toBeNull()

    const cancelled = editedConversions(args, new Set([`${GOAL}|biddable`]), () => undefined)
    expect(cancelled).toEqual({ account_goals: [], changes: raw().changes })

    const next = parsed({ ...raw(), ...cancelled })
    expect(conversionRows(next, args).map((row) => row.setting)).toEqual([
      "primary",
      "default_value",
    ])
    // Cancelling changes the request Google checked, so it must check again.
    expect(conversionsBlock(next, args)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )

    const undone = restoredConversions(next, [
      { key: GOAL, kind: "goal", reference: goal, setting: "biddable", value: false },
    ])
    expect(undone.account_goals).toEqual([{ goal, biddable: false }])
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
      googleAdsUpdateConversionsPresenter.render(
        props(
          {
            id: "conversions-1",
            kind: "approval",
            name: "google_ads_update_conversions",
            status: "awaiting_approval",
            args: raw(),
          },
          true
        )
      )
    )
    expect(approval).toContain("Bidding will optimise for different conversions")

    const result = html(
      googleAdsUpdateConversionsPresenter.render(
        props({
          id: "conversions-2",
          kind: "result",
          name: "google_ads_update_conversions",
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
                  currency: "GBP",
                  items: [
                    {
                      resource_name: ACTION,
                      kind: "conversion_action",
                      name: "Newsletter Sign-Up",
                      read_back: true,
                      settings: [
                        {
                          setting: "primary",
                          before: true,
                          requested: false,
                          after: false,
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
    expect(result).toContain("Secondary")
  })
})
