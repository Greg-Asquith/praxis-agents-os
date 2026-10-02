import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { EditedValues } from "@/components/tool-ui/edited-values"
import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { ToolUi } from "@/features/tools/types"
import type { ToolActivity } from "@/integrations/contract"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import {
  activationNotes,
  parseStatusChangeArgs,
  parseStatusChangeResult,
} from "@/integrations/meta_ads/lib/status-change"
import { metaAdsUpdateStatusPresenter } from "@/integrations/meta_ads/presenters/update-status"

const adReference = {
  version: 1,
  entity_kind: "meta_ads_ad",
  label: "Spring Ad",
  scope_label: "Example ad account",
  account_id: "111",
  ad_id: "333",
  status: "PAUSED",
}
const campaignReference = {
  version: 1,
  entity_kind: "meta_ads_campaign",
  label: "Spring Campaign",
  account_id: "111",
  campaign_id: "1",
  status: "PAUSED",
  currency: "EUR",
}
const reviewedArgs = {
  status: "ACTIVE",
  campaigns: [campaignReference],
  ads: [adReference],
  _delivery: { "333": { blocked_by: ["ad_set"] }, "1": { starting_children: 2 } },
  _reviewed_selection: { status: "ACTIVE", objects: ["campaign:1", "ad:333"] },
}
const APPROVE_DISABLED = /<button[^>]*\sdisabled=""[^>]*>Approve/

describe("Meta Ads status links and cascade", () => {
  it("builds Ads Manager links only from numeric ids", () => {
    expect(adsManagerObjectUrl("adset", "111", "222")).toBe(
      "https://adsmanager.facebook.com/adsmanager/manage/adsets?act=111&selected_adset_ids=222"
    )
    expect(adsManagerObjectUrl("ad", "111", "2&x=1")).toBeNull()
    expect(adsManagerObjectUrl("ad", "", "222")).toBeNull()
  })

  it("shows blocked, already-on, idle, and partial totals without misstating spend", () => {
    const args = parseStatusChangeArgs({
      status: "ACTIVE",
      campaigns: [
        campaignReference,
        { ...campaignReference, campaign_id: "2" },
        { ...campaignReference, campaign_id: "3" },
        { ...campaignReference, campaign_id: "4", budget: { kind: "daily", amount: "25" } },
        { ...campaignReference, campaign_id: "5", budget: { kind: "daily", amount: "25" } },
      ],
      _delivery: {
        "1": { blocked_by: [], already_on: true },
        "2": { blocked_by: [], starting_children: 2, budgets_incomplete: true },
        "3": { blocked_by: [], starting_children: 4, daily_budget: "40", budgets_incomplete: true },
        "4": { blocked_by: [], starting_children: 0 },
        "5": { blocked_by: [], starting_children: 0, children_truncated: true },
      },
    })
    const notes = args?.targets.map((target) => activationNotes(target, args.delivery[target.id]))

    expect(notes?.[0]).toHaveLength(1)
    expect(notes?.[1]?.join(" ")).not.toMatch(/€|0\.00/)
    expect(notes?.[2]?.[1]).toContain("at least €40.00")
    // A complete zero count holds the budget without claiming spend; a truncated one doesn't.
    expect(notes?.[3]?.join(" ")).not.toMatch(/spending/)
    expect(notes?.[4]?.join(" ")).toMatch(/spending/)
  })

  it("rejects malformed arguments and results", () => {
    expect(parseStatusChangeArgs({ status: "ARCHIVED", ads: [adReference] })).toBeNull()
    expect(parseStatusChangeArgs({ status: "PAUSED" })).toBeNull()
    expect(parseStatusChangeArgs({ status: "PAUSED", ads: [{ label: "x" }] })).toBeNull()
    expect(parseStatusChangeResult(resultData([{ ...object(), outcome: "weird" }]))).toBeNull()
  })
})

describe("Meta Ads update status presenter", () => {
  it("allows approval only while the evidence matches the selection", () => {
    const reviewed = render(approval({}))
    expect(reviewed).not.toMatch(APPROVE_DISABLED)
    expect(reviewed).not.toContain("Check Changes")
    expect(reviewed).toContain('rel="noreferrer"')

    for (const edits of [{ status: "PAUSED" }, { campaigns: [] }, { campaigns: null }]) {
      const edited = render(approval(edits))
      expect(edited).toMatch(APPROVE_DISABLED)
      expect(edited).toContain("Check Changes")
    }
  })

  it("asks for a check when the selection was never reviewed", () => {
    const { _reviewed_selection: _removed, ...unreviewed } = reviewedArgs
    expect(render(approval({}, unreviewed))).toMatch(APPROVE_DISABLED)
  })

  it("renders settled outcomes with delivery status", () => {
    const html = render(
      settled(resultEntry(resultData([object({ effective_status: "PENDING_REVIEW" })])))
    )
    expect(html).toContain("Spring Ad")
    expect(html).toContain("Pending Review")
  })

  it("shows the returned status and a warning when the change could not be confirmed", () => {
    const html = render(
      settled(
        resultEntry(
          resultData([
            object({ outcome: "unverified", status: "PAUSED", effective_status: "WITH_ISSUES" }),
          ]),
          {
            status: "error",
            error_code: "unverified_mutation",
          }
        )
      )
    )
    expect(html).toContain("Spring Ad")
    expect(html).toContain("verify whether Meta Ads updated")
    // The status Meta returned after the change stays visible beside the warning.
    expect(html).toContain("With Issues")
  })

  it("marks a successful reply whose every row failed as failed and keeps the rows", () => {
    const failed = object({
      outcome: "failed",
      status: null,
      effective_status: null,
      error_code: "IntegrationPermissionError",
      message: "Meta rejected the change.",
    })
    const html = render(settled(resultEntry(resultData([failed]))))
    expect(html).toContain("Meta Ads didn&#x27;t make any of these changes.")
    expect(html).toContain("Meta rejected the change.")
  })

  it("shows failure targets when the whole change failed", () => {
    const html = render(
      settled(
        resultEntry(null, {
          status: "error",
          error_code: "permission_denied",
          error_message: "Meta rejected the change.",
        })
      )
    )
    expect(html).toContain("Meta rejected the change.")
    expect(html).toContain("Spring Ad")
  })
})

function approval(edits: EditedValues, args: Record<string, unknown> = reviewedArgs) {
  const controls = {
    decision: { decision: "pending" as const, edits, message: "" as const },
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    onReview: vi.fn(),
    pendingCount: 1,
    submitting: false,
  }
  return metaAdsUpdateStatusPresenter.render(
    props(
      {
        id: "a1",
        kind: "approval",
        name: "meta_ads_update_status",
        status: "awaiting_approval",
        args,
      },
      controls
    )
  )
}

function object(overrides: Record<string, unknown> = {}) {
  return {
    object_type: "ad",
    object_id: "333",
    object_name: "Spring Ad",
    campaign_id: "1",
    adset_id: "222",
    previous_status: "PAUSED",
    previous_effective_status: "PAUSED",
    status: "ACTIVE",
    effective_status: "ACTIVE",
    outcome: "updated",
    error_code: null,
    message: null,
    ...overrides,
  }
}

function resultData(objects: unknown[]) {
  return { account_id: "111", requested_status: "ACTIVE", objects }
}

function resultEntry(data: unknown, overrides: Record<string, unknown> = {}) {
  return {
    provider_key: "meta_ads",
    external_id: "111",
    display_name: "Example ad account",
    status: "success",
    data,
    error_code: null,
    error_message: null,
    ...overrides,
  }
}

function settled(entry: unknown) {
  return metaAdsUpdateStatusPresenter.render(
    props({
      id: "r1",
      kind: "result",
      name: "meta_ads_update_status",
      status: "completed",
      args: { status: "ACTIVE", ads: [adReference] },
      result: { results: [entry] },
    })
  )
}

function props(activity: ToolActivity, approvalDecision?: ToolApprovalDecisionControls) {
  return {
    activity,
    ...(approvalDecision ? { approvalDecision, ui: toolUi() } : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "meta_ads",
  }
}

// The editable status field from the backend presentation. Entity pickers need a live
// conversation to verify targets, so list edits go straight into the decision edits.
function toolUi(): ToolUi {
  return {
    approval_prompt: "",
    approval_title: "",
    approve_label: "Approve & Update",
    arg_fields: [
      {
        key: "status",
        label: "Status",
        format: "text",
        editable: true,
        min_rows: 0,
        options: ["ACTIVE", "PAUSED"],
        placeholder: "",
        secondary: false,
      },
    ],
    completed_label: "",
    failed_label: "",
    icon: "meta_ads",
    result_fields: [],
    running_label: "",
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
