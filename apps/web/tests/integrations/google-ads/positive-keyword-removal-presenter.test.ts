import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity, ToolRowPresenter } from "@/integrations/contract"
import { googleAdsRemovePositiveKeywordsPresenter as presenter } from "@/integrations/google_ads/presenters/remove-positive-keywords"

function keyword(adGroupId = "20") {
  return {
    entity_kind: "google_ads_keyword",
    customer_id: "333",
    campaign_id: "10",
    ad_group_id: adGroupId,
    criterion_id: "90",
    text: "running shoes",
    label: "running shoes",
    scope_label: `Search · Shoes ${adGroupId}`,
    match_type: "EXACT",
    status: "PAUSED",
    final_urls: [],
    final_mobile_urls: [],
    url_custom_parameters: [],
  }
}

function render(
  status: ToolActivity["status"],
  result?: unknown,
  args: unknown = { keywords: [keyword(), keyword("21")] }
) {
  const props: Parameters<ToolRowPresenter["render"]>[0] = {
    activity: {
      args,
      id: "removal",
      kind: "approval",
      name: "google_ads_remove_keywords",
      status,
      ...(result ? { result } : {}),
    },
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
    ...(status === "awaiting_approval"
      ? {
          approvalDecision: {
            decision: { decision: "pending", edits: {}, message: "" },
            error: null,
            onDecisionChange: vi.fn(),
            onRetry: vi.fn(),
            pendingCount: 1,
            submitting: false,
          },
        }
      : {}),
  }
  return renderToStaticMarkup(createElement("div", null, presenter.render(props)))
}

function sample(adGroupId: string, outcome: "removed" | "failed" | "unverified") {
  return {
    reference: keyword(adGroupId),
    previous_status: "PAUSED",
    resulting_status: outcome === "removed" ? "REMOVED" : outcome === "failed" ? "PAUSED" : null,
    outcome,
    message: outcome === "failed" ? "Removal rejected" : null,
    error_code: null,
  }
}

function result() {
  return {
    results: [
      {
        provider_key: "google_ads",
        resource_type: "google_ads_account",
        external_id: "333",
        display_name: "Retail account",
        connection_id: "connection",
        integration_resource_id: "resource",
        status: "success",
        error_code: null,
        error_message: null,
        data: {
          counts: { removed: 1, failed: 1, unverified: 1 },
          samples_truncated: false,
          samples: {
            removed: [sample("20", "removed")],
            failed: [sample("21", "failed")],
            unverified: [sample("22", "unverified")],
          },
        },
      },
    ],
  }
}

describe("positive keyword removal presenter", () => {
  it("shows selected keyword labels as failure chips", () => {
    expect(render("failed")).toMatch(/data-slot="badge"[^>]*>running shoes/)
  })

  it("shows destructive approval with both ad groups and account context", () => {
    const html = render("awaiting_approval")
    expect(html).toContain("cannot be undone")
    expect(html).toContain("cannot be re-enabled")
    expect(html).toContain("Approve &amp; Remove")
    expect(html).toContain("Shoes 20")
    expect(html).toContain("Shoes 21")
    expect(html).toContain("333")
    expect(html).toContain("Account 333 · Exact")
    expect(html).not.toContain("Account 333 · EXACT")
  })

  it("shows exact per-row outcomes and before/requested/after states", () => {
    const html = render("completed", result())
    for (const value of [
      "Retail account",
      "Shoes 20",
      "Shoes 21",
      "Shoes 22",
      "Removal rejected",
      "Unverified",
      "Before",
      "Requested",
      "After",
    ]) {
      expect(html).toContain(value)
    }
  })

  it.each(["duplicate", "counts", "after", "truncated"])(
    "rejects contradictory %s evidence",
    (failure) => {
      const value = result()
      const data = value.results[0]?.data
      if (!data) throw new Error("Missing result fixture")
      const failed = data.samples.failed[0]
      const removed = data.samples.removed[0]
      if (!failed || !removed) throw new Error("Missing outcome fixture")
      if (failure === "duplicate") failed.reference = keyword("20")
      if (failure === "counts") data.counts.failed = 0
      if (failure === "after") removed.resulting_status = "PAUSED"
      if (failure === "truncated") data.samples_truncated = true
      expect(render("completed", value)).toContain("couldn&#x27;t confirm")
    }
  )

  it("blocks empty and duplicate approvals", () => {
    for (const keywords of [[], [keyword(), keyword()]]) {
      expect(render("awaiting_approval", undefined, { keywords })).toContain(
        "can&#x27;t be approved"
      )
    }
  })

  it.each(["running", "failed", "denied"] as const)(
    "renders the %s state without claiming removal",
    (status) => {
      const html = render(status)
      expect(html).not.toContain("Google Ads keyword removal results")
      expect(html).toContain(
        status === "denied"
          ? "Nothing was removed"
          : status === "failed"
            ? "The keywords could not be removed"
            : "Removing keywords…"
      )
    }
  )
})
