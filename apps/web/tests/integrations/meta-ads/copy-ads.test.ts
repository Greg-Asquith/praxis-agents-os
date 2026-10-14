// apps/web/tests/integrations/meta-ads/copy-ads.test.ts

import { createElement, type ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import { metaAdsCopyAdsPresenter } from "@/integrations/meta_ads/presenters/copy-ads"

const APPROVE_DISABLED = /<button[^>]*\sdisabled=""[^>]*>Approve/

function copy(adSetId: string, extra: Record<string, unknown> = {}) {
  return {
    ad: {
      entity_kind: "meta_ads_ad",
      account_id: "123",
      campaign_id: "9",
      adset_id: "8",
      ad_id: "500",
      label: "Winner",
    },
    ad_set: {
      entity_kind: "meta_ads_ad_set",
      account_id: "123",
      campaign_id: "9",
      adset_id: adSetId,
      label: `Ad set ${adSetId}`,
    },
    status: "paused",
    ...extra,
  }
}

function display(copies: unknown[]) {
  return {
    copies,
    _account: { account_id: "123", resource_id: "r" },
    _account_name: "Acme UK",
    _currency: "GBP",
    _ad_sets: {
      "7": { adset_id: "7", label: "Lookalikes", status: "ACTIVE", effective_status: "ACTIVE" },
    },
    _sources: {
      "500": {
        name: "Winner",
        format: "image",
        excerpt: "Spring sale on now",
        media: { key: "image:abc", media_type: "image" },
        automatic_changes: ["Relevant comments"],
        ai_generated: false,
      },
    },
  }
}

describe("Meta Ads copy ads presenter", () => {
  it("renders the approval and blocks two copies sharing a name in one ad set", () => {
    const ready = render(approval(display([copy("7")])))
    expect(ready).not.toMatch(APPROVE_DISABLED)
    expect(ready).toContain("Automatic changes on: Relevant comments")

    const clash = render(
      approval(display([copy("7"), copy("7", { ad: { ...copy("7").ad, ad_id: "501" } })]))
    )
    expect(clash).toMatch(APPROVE_DISABLED)
  })

  it("shows each copy's outcome when only some were made", () => {
    const html = render(
      metaAdsCopyAdsPresenter.render(
        props({
          id: "r1",
          kind: "result",
          name: "meta_ads_copy_ads",
          status: "completed",
          args: display([copy("7"), copy("6")]),
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
                  copies: [
                    copiedAd({}),
                    copiedAd({
                      adset_id: "6",
                      outcome: "failed",
                      ad_id: null,
                      message: "Ad set is full.",
                    }),
                  ],
                },
              },
            ],
          },
        })
      )
    )

    expect(html).toContain("Ad set is full.")
    expect(html).toContain('href="https://fb.me/preview"')
  })
})

function copiedAd(values: Record<string, unknown>) {
  return {
    source_ad_id: "500",
    source_name: "Winner",
    name: "Winner",
    adset_id: "7",
    adset_name: "Lookalikes",
    format: "image",
    requested_status: "paused",
    paused_for_ai: false,
    outcome: "copied",
    recovered: false,
    verified: true,
    ad_id: "900",
    effective_status: "PENDING_REVIEW",
    review: "in_review",
    review_reasons: [],
    unexpected_changes: [],
    preview_url: "https://fb.me/preview",
    error_code: null,
    message: null,
    ...values,
  }
}

function approval(args: Record<string, unknown>) {
  return metaAdsCopyAdsPresenter.render(
    props(
      { id: "a1", kind: "approval", name: "meta_ads_copy_ads", status: "awaiting_approval", args },
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
