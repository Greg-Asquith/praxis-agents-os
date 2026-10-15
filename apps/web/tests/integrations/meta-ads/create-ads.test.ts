// apps/web/tests/integrations/meta-ads/create-ads.test.ts

import { describe, expect, it } from "vitest"

import { parseCreateAdsArgs, type CreateAdsArgs } from "@/integrations/meta_ads/lib/create-ads-args"
import { allowedButtons } from "@/integrations/meta_ads/lib/call-to-action"
import {
  adRows,
  adSetDelivery,
  createAdsProblem,
} from "@/integrations/meta_ads/lib/create-ads-checks"
import {
  editAd,
  editSetting,
  editStatus,
  moveCard,
  setAdSets,
  setCardMedia,
  setFollowsShared,
  toggleChange,
} from "@/integrations/meta_ads/lib/create-ads-edits"
import { metaAdsCreateAdsPresenter } from "@/integrations/meta_ads/presenters/create-ads"
import { APPROVE_DISABLED, props, render } from "./presenter-harness"

const page = {
  version: 1,
  entity_kind: "meta_ads_page",
  account_id: "123",
  page_id: "11",
  label: "Acme",
}
const image = {
  version: 1,
  entity_kind: "meta_ads_media",
  account_id: "123",
  media_type: "image",
  image_hash: "abc",
  label: "hero.jpg",
}
const adSet = {
  version: 1,
  entity_kind: "meta_ads_ad_set",
  account_id: "123",
  campaign_id: "9",
  adset_id: "8",
  label: "Prospecting",
}
function design(name: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    name,
    ad_sets: [adSet],
    format: "image",
    primary_text: "Spring sale on now",
    headline: "20% off",
    media: image,
    ...extra,
  }
}

function display(overrides: Record<string, unknown> = {}) {
  return {
    ads: [
      design("Spring"),
      design("Autumn", { link: "https://example.com/autumn", call_to_action: "SIGN_UP" }),
    ],
    page,
    link: "https://example.com/spring",
    call_to_action: "SHOP_NOW",
    status: "paused",
    _account_name: "Acme UK",
    _currency: "GBP",
    _ad_sets: {
      "8": {
        ...adSet,
        status: "ACTIVE",
        effective_status: "ACTIVE",
        objective: "OUTCOME_SALES",
        budget: { kind: "daily", amount: "150", remaining: null },
      },
    },
    _media: { "image:abc": { ...image, width: 1080, height: 1080 } },
    _files: [],
    _automatic_change_catalogue: [change("image_touchups", false), change("image_uncrop", true)],
    _buttons: {
      website: ["LEARN_MORE", "SHOP_NOW", "SIGN_UP", "NO_BUTTON"],
      app: ["INSTALL_MOBILE_APP", "USE_APP"],
    },
    ...overrides,
  }
}

function change(key: string, aiGenerated: boolean) {
  return {
    key,
    label: key,
    description: "",
    group: "media",
    ai_generated: aiGenerated,
    formats: ["image"],
  }
}

function parsed(overrides: Record<string, unknown> = {}): CreateAdsArgs {
  const args = parseCreateAdsArgs(display(overrides))
  if (!args) throw new Error("fixture didn't parse")
  return args
}

describe("Meta Ads create ads model", () => {
  it("applies shared values to every ad, and an ad's own value wins", () => {
    const [shared, own] = adRows(parsed())

    expect([shared?.link, shared?.callToAction]).toEqual(["https://example.com/spring", "SHOP_NOW"])
    expect([own?.link, own?.callToAction]).toEqual(["https://example.com/autumn", "SIGN_UP"])
  })

  it("resets an override to the shared value without touching anything else in the ad", () => {
    const args = parsed()
    const edited = editAd(args, 1, "link", null)

    expect(adRows(parsed({ ads: edited }))[1]?.link).toBe("https://example.com/spring")
    const { link: _link, ...unchanged } = design("Autumn", {
      link: "https://example.com/autumn",
      call_to_action: "SIGN_UP",
    })
    expect(edited[1]).toEqual(unchanged)
    expect(edited[0]).toBe(args.rawAds[0])
  })

  it("keeps an ad's own settings when the shared ones change later", () => {
    const own = setFollowsShared(parsed(), 0, false)
    expect(adRows(parsed({ ads: own, call_to_action: "SIGN_UP" }))[0]?.callToAction).toBe(
      "SHOP_NOW"
    )
  })

  it("moves a carousel card and keeps each card's own media", () => {
    const cards = [
      { media: image, headline: "First" },
      { media: { ...image, image_hash: "def" }, headline: "Second" },
    ]
    const carousel = design("Carousel", {
      format: "carousel",
      headline: undefined,
      media: undefined,
      cards,
    })
    const args = parsed({ ads: [carousel] })

    const moved = moveCard(args, 0, 0, 1)

    expect(moved[0]?.["cards"]).toEqual([cards[1], cards[0]])
    expect(moveCard(args, 0, 1, 1)[0]?.["cards"]).toEqual(cards)
  })

  it("swaps a video card for an image without the thumbnail only video cards take", () => {
    const video = { ...image, media_type: "video", image_hash: undefined, video_id: "77" }
    const cards = [
      { media: video, thumbnail: image, headline: "First" },
      { media: { ...image, image_hash: "def" }, headline: "Second" },
    ]
    const args = parsed({
      ads: [
        design("Carousel", { format: "carousel", headline: undefined, media: undefined, cards }),
      ],
    })
    const file = { entity_kind: "file", entity_id: "f1", label: "new.png" }

    const [swapped] = setCardMedia(args, 0, 0, file)[0]?.["cards"] as Record<string, unknown>[]

    expect(swapped).toEqual({ media: file, headline: "First" })
    const [kept] = setCardMedia(args, 0, 0, { ...video, video_id: "78" })[0]?.["cards"] as Record<
      string,
      unknown
    >[]
    expect(kept?.["thumbnail"]).toEqual(image)
  })

  it("blocks a carousel that repeats media", () => {
    const cards = [
      { media: image, headline: "First" },
      { media: image, headline: "Second" },
    ]
    const carousel = design("Carousel", { format: "carousel", headline: undefined, cards })

    expect(createAdsProblem(parsed({ ads: [{ ...carousel, media: undefined }] }))).not.toBeNull()
  })

  it("starts every ad paused when an AI-generated change is on", () => {
    const rows = adRows(parsed({ status: "active", automatic_changes: ["image_uncrop"] }))

    expect(rows.every((row) => row.status === "paused" && row.statusForced)).toBe(true)
    expect(
      adRows(parsed({ status: "active", automatic_changes: ["image_touchups"] }))[0]?.status
    ).toBe("active")
  })

  it("blocks approval for an ad Meta would reject, but not for a long headline", () => {
    expect(createAdsProblem(parsed())).toBeNull()
    expect(createAdsProblem(parsed({ link: "http://example.com" }))).not.toBeNull()
    const app = { ...display()._ad_sets["8"], objective: "OUTCOME_APP_PROMOTION" }
    expect(createAdsProblem(parsed({ _ad_sets: { "8": app } }))).not.toBeNull()
    const long = design("Spring", { headline: "A headline far longer than forty characters" })
    const [row] = adRows(parsed({ ads: [long] }))
    expect(row?.check).toBe("warning")
  })

  it("blocks what the server would refuse after an edit that looks fine", () => {
    const tags = Array.from({ length: 31 }, (_, index) => `#tag${String(index)}`).join(" ")

    expect(
      createAdsProblem(parsed({ ads: [design("Spring", { primary_text: tags })] }))
    ).not.toBeNull()
    expect(createAdsProblem(parsed({ link: "https://example.com/spring sale" }))).not.toBeNull()
    expect(createAdsProblem(parsed({ ads: [design("A".repeat(201))] }))).not.toBeNull()
    const adSets = Array.from({ length: 11 }, (_, index) => ({ ...adSet, adset_id: String(index) }))
    expect(
      createAdsProblem(parsed({ ads: [design("Spring", { ad_sets: adSets })] }))
    ).not.toBeNull()
  })

  it("says ads created active spend only where their ad set and campaign are on", () => {
    const delivery = (status: string, adSetValues: Record<string, unknown> = {}) => {
      const args = parsed({
        status,
        _ad_sets: { "8": { ...display()._ad_sets["8"], ...adSetValues } },
      })
      return adSetDelivery(args, adRows(args)).get("8")
    }

    expect(delivery("active")).toBe("runs")
    expect(delivery("active", { effective_status: "CAMPAIGN_PAUSED" })).toBe("campaign_off")
    expect(delivery("active", { status: "PAUSED" })).toBe("ad_set_off")
    expect(delivery("paused")).toBe("paused")
  })

  it("offers only the buttons every ad set's goal accepts", () => {
    const lists = { website: ["LEARN_MORE", "DOWNLOAD"], app: ["DOWNLOAD", "USE_APP"] }

    expect(allowedButtons(lists, ["OUTCOME_SALES", "OUTCOME_APP_PROMOTION"])).toEqual(["DOWNLOAD"])
  })

  it("sets every ad's status in one edit, clearing an ad's own status", () => {
    expect(editStatus(parsed(), "active")).toEqual({ status: "active" })

    const args = parsed({ ads: [design("Spring", { status: "active" }), design("Autumn")] })
    const edits = editStatus(args, "paused")
    expect(adRows(parsed(edits)).map((row) => row.status)).toEqual(["paused", "paused"])
  })

  it("moves an ad to other ad sets, never to none", () => {
    const other = { ...adSet, adset_id: "9", label: "Retargeting" }
    const args = parsed()
    const edited = setAdSets(args, 0, [adSet, other])

    const rows = adRows(parsed({ ads: edited }))
    expect(rows[0]?.ad.adSetIds).toEqual(["8", "9"])
    expect(rows[1]?.ad.adSetIds).toEqual(["8"])
    expect(parsed({ ads: edited }).adSets.get("9")?.name).toBe("Retargeting")
    expect(setAdSets(args, 0, [])).toEqual(args.rawAds)
  })

  it("edits the shared link while an ad follows it, and the ad's own once it has one", () => {
    const args = parsed()

    expect(editSetting(args, 0, "link", "https://example.com/new")).toEqual({
      field: "link",
      value: "https://example.com/new",
    })
    expect(editSetting(args, 1, "link", "https://example.com/new").field).toBe("ads")
  })

  it("turns the last advanced setting off by clearing the list", () => {
    const args = parsed({ automatic_changes: ["image_touchups", "image_uncrop"] })

    expect(toggleChange(args, "image_touchups", false)).toEqual(["image_uncrop"])
    expect(
      toggleChange(parsed({ automatic_changes: ["image_uncrop"] }), "image_uncrop", false)
    ).toBeNull()
  })

  it("renders the approval card and shows a hidden field's error while blocking approval", () => {
    const ready = render(approval(display()))
    expect(ready).not.toMatch(APPROVE_DISABLED)

    const broken = render(approval(display({ link: "not a link" })))
    expect(broken).toMatch(APPROVE_DISABLED)
    expect(broken).toMatch(/<input[^>]*aria-invalid="true"[^>]*value="not a link"/)
  })

  it("renders an existing post from Meta's own read as plain text, and blocks one it lost", () => {
    const post = {
      version: 1,
      entity_kind: "meta_ads_post",
      account_id: "123",
      source: "facebook",
      post_id: "11_500",
      page_id: "11",
      label: "Facebook post",
    }
    const postAd = { name: "Best post", ad_sets: [adSet], format: "existing_post", post }
    const found = {
      "facebook:11_500": { ...post, excerpt: "<b>Our best day</b>", boostable: null },
    }

    const html = render(approval(display({ ads: [postAd], _posts: found })))
    expect(html).toContain("&lt;b&gt;Our best day&lt;/b&gt;")
    expect(html).not.toMatch(APPROVE_DISABLED)
    expect(render(approval(display({ ads: [postAd], _posts: {} })))).toMatch(APPROVE_DISABLED)
  })

  it("shows each ad's outcome when only some were created", () => {
    const html = render(
      metaAdsCreateAdsPresenter.render(
        props({
          id: "r1",
          kind: "result",
          name: "meta_ads_create_ads",
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
                data: result([
                  createdAd({}),
                  createdAd({
                    name: "Autumn",
                    outcome: "failed",
                    ad_id: null,
                    message: "Image too small.",
                  }),
                ]),
              },
            ],
          },
        })
      )
    )

    expect(html).toContain("Image too small.")
    expect(html).toContain('href="https://fb.me/preview"')
  })
})

function createdAd(values: Record<string, unknown>) {
  return {
    design_index: 0,
    name: "Spring",
    adset_id: "8",
    adset_name: "Prospecting",
    format: "image",
    requested_status: "paused",
    outcome: "created",
    recovered: false,
    verified: true,
    ad_id: "900",
    creative_id: "500",
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

function result(ads: unknown[]) {
  return { account_id: "123", ads, uploads: [], automatic_changes: [], created_off_for_ai: false }
}

function approval(args: Record<string, unknown>) {
  return metaAdsCreateAdsPresenter.render(
    props(
      {
        id: "a1",
        kind: "approval",
        name: "meta_ads_create_ads",
        status: "awaiting_approval",
        args,
      },
      true
    )
  )
}
