// apps/web/tests/integrations/google-ads/status-change.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  editedChanges,
  parseStatusChangeArgs,
  statusApproveLabel,
  statusBlock,
  statusCounts,
  statusPrompt,
  statusResourceName,
  statusRows,
  type StatusChangeArgs,
} from "@/integrations/google_ads/lib/status-change"
import {
  parseStatusChangeResult,
  resultSummary,
} from "@/integrations/google_ads/lib/status-change-result"
import { googleAdsUpdateStatusPresenter } from "@/integrations/google_ads/presenters/update-status"

const CUSTOMER = "1234567890"
const campaign = {
  entity_kind: "google_ads_campaign",
  customer_id: CUSTOMER,
  campaign_id: "10",
  label: "Trail Running Shoes",
}
const adGroup = {
  entity_kind: "google_ads_ad_group",
  customer_id: CUSTOMER,
  campaign_id: "10",
  ad_group_id: "20",
  label: "Shoes Exact",
}
const ad = {
  entity_kind: "google_ads_ad",
  customer_id: CUSTOMER,
  campaign_id: "10",
  ad_group_id: "20",
  ad_id: "30",
  label: "Spring Ad",
}
const keyword = {
  entity_kind: "google_ads_keyword",
  customer_id: CUSTOMER,
  campaign_id: "10",
  ad_group_id: "20",
  criterion_id: "40",
  label: "running shoes",
  text: "running shoes",
  match_type: "EXACT",
  status: "ENABLED",
  cpc_bid_micros: "1500000",
}

const RESOURCES = {
  campaign: `customers/${CUSTOMER}/campaigns/10`,
  adGroup: `customers/${CUSTOMER}/adGroups/20`,
  ad: `customers/${CUSTOMER}/adGroupAds/20~30`,
  keyword: `customers/${CUSTOMER}/adGroupCriteria/20~40`,
}

function check(over: Record<string, unknown> = {}) {
  return {
    unavailable: false,
    kind: "campaign",
    name: "x",
    campaign_id: "10",
    campaign_name: "Trail Running Shoes",
    campaign_status: "ENABLED",
    ad_group_id: "20",
    ad_group_name: "Shoes Exact",
    ad_group_status: "ENABLED",
    status: "ENABLED",
    requested: "PAUSED",
    problem: null,
    ...over,
  }
}

function args(over: Record<string, unknown> = {}) {
  return {
    changes: [
      { kind: "campaign", campaign, status: "PAUSED" },
      { kind: "ad_group", ad_group: adGroup, status: "ENABLED" },
      { kind: "ad", ad, status: "ENABLED" },
      { kind: "keyword", keyword, status: "PAUSED" },
    ],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: {
      [RESOURCES.campaign]: check(),
      [RESOURCES.adGroup]: check({ status: "PAUSED", requested: "ENABLED" }),
      [RESOURCES.ad]: check({ status: "PAUSED", requested: "ENABLED" }),
      [RESOURCES.keyword]: check({ status: "ENABLED", requested: "PAUSED" }),
    },
    ...over,
  }
}

function parsed(value: unknown = args()): StatusChangeArgs {
  const result = parseStatusChangeArgs(value)
  if (!result) throw new Error("expected status args")
  return result
}

describe("Google Ads status arguments", () => {
  it("keys each object by its resource name and rejects malformed or repeated changes", () => {
    expect(parsed().items.map((item) => item.key)).toEqual(Object.values(RESOURCES))
    expect(statusResourceName("asset_group", CUSTOMER, { asset_group_id: "9" })).toBe(
      `customers/${CUSTOMER}/assetGroups/9`
    )
    const first = { kind: "campaign", campaign, status: "PAUSED" }
    expect(parseStatusChangeArgs({ changes: [first, first] })).toBeNull()
    expect(parseStatusChangeArgs({ changes: [{ ...first, status: "REMOVED" }] })).toBeNull()
    expect(
      parseStatusChangeArgs({ changes: [{ kind: "ad", ad: campaign, status: "PAUSED" }] })
    ).toBeNull()
  })

  it("blocks an item with no check or an unavailable one", () => {
    const base = args()
    const value = {
      ...base,
      _checks: {
        [RESOURCES.campaign]: { unavailable: true },
        [RESOURCES.ad]: base._checks[RESOURCES.ad],
      },
    }
    const rows = statusRows(parsed(value), parsed(value))
    expect(rows.map((row) => row.problem !== null)).toEqual([true, true, false, true])
  })

  it("shows a rejection only while the status still equals the one checked", () => {
    const rejected = args({
      _checks: {
        ...args()._checks,
        [RESOURCES.campaign]: check({ problem: "Campaign is removed." }),
      },
    })
    const proposed = parsed(rejected)
    expect(statusRows(proposed, proposed)[0]?.problem).toBe("Campaign is removed.")
    const flipped = parsed({
      ...rejected,
      changes: [{ kind: "campaign", campaign, status: "ENABLED" }, ...rejected.changes.slice(1)],
    })
    expect(statusRows(proposed, flipped)[0]?.problem).toBeNull()
  })
})

describe("Google Ads status rows", () => {
  it("counts only changes that will run and warns for items under an off parent", () => {
    // The ad group is turned on under a campaign that is turned off in the same request.
    const proposed = parsed()
    const rows = statusRows(proposed, proposed)
    const counts = statusCounts(rows)
    expect(counts).toMatchObject({ turnOff: 2, turnOn: 2, alreadySet: 0, apply: 4, campaigns: 1 })
    expect(rows[1]?.wontShow).toBe("Won't show ads until Trail Running Shoes is on.")
    // The ad's ad group is turned on in the same request, but its campaign stays off.
    expect(rows[2]?.wontShow).toBe("Won't show ads until Trail Running Shoes is on.")
    expect(statusApproveLabel(counts)).toBe("Apply 4 Changes")
    expect(statusPrompt(counts, ["Northwind"])).toBe("Turn off 2 items and turn on 2 in Northwind.")
  })

  it("treats an unchanged status as already set and leaves it out of the approve count", () => {
    const value = args({
      _checks: { ...args()._checks, [RESOURCES.campaign]: check({ status: "PAUSED" }) },
    })
    const proposed = parsed(value)
    const counts = statusCounts(statusRows(proposed, proposed))
    expect(counts).toMatchObject({ alreadySet: 1, apply: 3 })
  })

  it("explains why approval is blocked for problems and for nothing left to apply", () => {
    const proposed = parsed()
    expect(statusBlock(proposed)).toBeNull()
    const noChecks = parsed({ ...args(), _checks: {} })
    expect(statusBlock(noChecks)).toMatch(/attention/)
    expect(statusBlock(parsed({ ...args(), changes: [] }))).toMatch(/cancelled/)
  })
})

describe("Google Ads status edits", () => {
  const proposed = parsed()
  const rows = statusRows(proposed, proposed)

  it("omits cancelled changes and sets bulk statuses while keeping reference fields", () => {
    const cancelled = editedChanges(rows, new Set([RESOURCES.ad]), { cancelled: true })
    expect(cancelled.map((change) => change["kind"])).toEqual(["campaign", "ad_group", "keyword"])

    const bulk = editedChanges(rows, new Set([RESOURCES.campaign, RESOURCES.keyword]), {
      status: "ENABLED",
    })
    expect(bulk.map((change) => change["status"])).toEqual([
      "ENABLED",
      "ENABLED",
      "ENABLED",
      "ENABLED",
    ])
    expect(bulk[3]).toEqual({ kind: "keyword", keyword, status: "ENABLED" })
  })

  it("restores a cancelled change in its original place without touching the others", () => {
    const afterCancel = parsed({
      ...args(),
      changes: editedChanges(rows, new Set([RESOURCES.adGroup]), { cancelled: true }),
    })
    const current = statusRows(proposed, afterCancel)
    expect(current.map((row) => row.cancelled)).toEqual([false, true, false, false])
    // A status edit never revives a cancelled change.
    expect(editedChanges(current, new Set([RESOURCES.adGroup]), { status: "PAUSED" })).toHaveLength(
      3
    )
    const restored = editedChanges(current, new Set([RESOURCES.adGroup]), { cancelled: false })
    expect(restored.map((change) => change["kind"])).toEqual([
      "campaign",
      "ad_group",
      "ad",
      "keyword",
    ])
  })
})

describe("Google Ads status results", () => {
  const object = (over: Record<string, unknown> = {}) => ({
    kind: "campaign",
    resource_name: RESOURCES.campaign,
    name: "Trail Running Shoes",
    campaign_id: "10",
    campaign_name: "Trail Running Shoes",
    before: "ENABLED",
    requested: "PAUSED",
    after: "PAUSED",
    outcome: "updated",
    error_code: null,
    message: null,
    ...over,
  })

  it("rejects an unknown outcome and summarises the counts", () => {
    expect(
      parseStatusChangeResult({ account_id: CUSTOMER, objects: [object({ outcome: "weird" })] })
    ).toBeNull()
    const result = parseStatusChangeResult({
      account_id: CUSTOMER,
      objects: [object(), object({ outcome: "already_set", resource_name: "b" })],
    })
    expect(result && resultSummary(result)).toBe("1 changed, 1 already set")
  })
})

describe("Google Ads update status card", () => {
  const baseProps = (activity: ToolActivity, withApproval = false) => ({
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
  const html = (node: ReactNode) => renderToStaticMarkup(createElement("div", null, node))

  it("renders the approval with the approve count and the result table", () => {
    const approval = html(
      googleAdsUpdateStatusPresenter.render(
        baseProps(
          {
            id: "status-1",
            kind: "approval",
            name: "google_ads_update_status",
            status: "awaiting_approval",
            args: args(),
          },
          true
        )
      )
    )
    expect(approval).toContain("Apply 4 Changes")

    const result = html(
      googleAdsUpdateStatusPresenter.render(
        baseProps({
          id: "status-2",
          kind: "result",
          name: "google_ads_update_status",
          status: "completed",
          args: args(),
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
                    object(),
                    object({ outcome: "failed", resource_name: "b", message: "No." }),
                  ],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("Failed")
  })
})

function object(over: Record<string, unknown> = {}) {
  return {
    kind: "campaign",
    resource_name: RESOURCES.campaign,
    name: "Trail Running Shoes",
    campaign_id: "10",
    campaign_name: "Trail Running Shoes",
    before: "ENABLED",
    requested: "PAUSED",
    after: "PAUSED",
    outcome: "updated",
    error_code: null,
    message: null,
    ...over,
  }
}
