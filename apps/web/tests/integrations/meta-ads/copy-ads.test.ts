// apps/web/tests/integrations/meta-ads/copy-ads.test.ts

import { describe, expect, it } from "vitest"

import { editCopy, parseCopyAdsArgs } from "@/integrations/meta_ads/lib/copy-ads"
import { metaAdsCopyAdsPresenter } from "@/integrations/meta_ads/presenters/copy-ads"
import { APPROVE_DISABLED, props, render } from "./presenter-harness"

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
    expect(render(approval(display([copy("7")])))).not.toMatch(APPROVE_DISABLED)

    const clash = render(
      approval(display([copy("7"), copy("7", { ad: { ...copy("7").ad, ad_id: "501" } })]))
    )
    expect(clash).toMatch(APPROVE_DISABLED)
  })

  it("blocks a copy into the source's own ad set or a repeat of the same place", () => {
    for (const copies of [[copy("8")], [copy("7"), copy("7", { name: "Other" })]]) {
      expect(render(approval(display(copies)))).toMatch(APPROVE_DISABLED)
    }
  })

  it("changes, adds, and removes copies without touching the others", () => {
    const args = parseCopyAdsArgs(display([copy("7"), copy("6")]))
    if (!args) throw new Error("expected copy args")
    const target = { entity_kind: "meta_ads_ad_set", adset_id: "5", label: "Ad set 5" }

    expect(editCopy(args, 0, { adSet: target })[0]).toMatchObject({ ad_set: target })
    expect(editCopy(args, 0, { remove: true })).toEqual([args.rawCopies[1]])
    expect(editCopy(args, 1, { copyInto: target })[2]).toEqual({
      ad: args.rawCopies[1]?.["ad"],
      ad_set: target,
      status: "paused",
    })
    expect(editCopy(args, 0, { name: "  " })[0]).not.toHaveProperty("name")
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
