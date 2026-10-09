// apps/web/src/integrations/meta_ads/lib/create-ads-edits.ts

import { DEFAULT_BUTTON } from "@/integrations/meta_ads/lib/call-to-action"
import {
  MAX_CARDS,
  MIN_CARDS,
  type AdDraft,
  type CreateAdsArgs,
  type MediaSlot,
  type MediaValue,
} from "@/integrations/meta_ads/lib/create-ads-args"
import { isRecord } from "@/lib/guards"

// The whole ads argument after an edit, which the server checks against the tool's model.
export type EditedAds = Record<string, unknown>[]

export type EditableAdKey =
  | "name"
  | "primary_text"
  | "headline"
  | "description"
  | "link"
  | "call_to_action"
  | "url_tags"
  | "status"
export type EditableCardKey = "headline" | "description" | "link" | "call_to_action"

/** Clears an optional field the operator emptied, keeping their spaces while they type. */
export function blankToNull(value: string): string | null {
  return value.trim() ? value : null
}

// The ad keys that override a shared setting, keyed by the shared value each overrides.
const SHARED_KEYS = ["link", "call_to_action", "url_tags", "status"] as const

function sharedValue(args: CreateAdsArgs, key: (typeof SHARED_KEYS)[number]): string | null {
  if (key === "link") return args.shared.link
  if (key === "call_to_action") return args.shared.callToAction ?? DEFAULT_BUTTON
  if (key === "url_tags") return args.shared.urlTags
  return args.shared.status
}

/** True when the ad sets none of the shared settings itself, so it follows them exactly. */
export function followsShared(ad: AdDraft): boolean {
  return Object.values(ad.overrides).every((value) => value === null)
}

/** Makes an ad follow the shared settings, or starts its own from a copy of them. */
export function setFollowsShared(args: CreateAdsArgs, index: number, on: boolean): EditedAds {
  return args.rawAds.map((ad, position) => {
    if (position !== index) return ad
    const rest = Object.fromEntries(
      Object.entries(ad).filter(([key]) => !(SHARED_KEYS as readonly string[]).includes(key))
    )
    if (on) return rest
    const own = Object.fromEntries(
      SHARED_KEYS.flatMap((key) => {
        const value = sharedValue(args, key)
        return value === null ? [] : [[key, value]]
      })
    )
    return { ...rest, ...own }
  })
}

// Edits rewrite the whole ads argument, keeping every field the card doesn't change.
export function editAd(
  args: CreateAdsArgs,
  index: number,
  key: EditableAdKey,
  value: string | null
): EditedAds {
  return args.rawAds.map((ad, position) => (position === index ? withValue(ad, key, value) : ad))
}

export function editCard(
  args: CreateAdsArgs,
  adIndex: number,
  cardIndex: number,
  key: EditableCardKey,
  value: string | null
): EditedAds {
  return updateCards(args, adIndex, (cards) =>
    cards.map((card, position) =>
      position === cardIndex && isRecord(card) ? withValue(card, key, value) : card
    )
  )
}

export function moveCard(
  args: CreateAdsArgs,
  adIndex: number,
  cardIndex: number,
  offset: -1 | 1
): EditedAds {
  return updateCards(args, adIndex, (cards) => {
    const target = cardIndex + offset
    if (target < 0 || target >= cards.length) return cards
    const next = [...cards]
    ;[next[cardIndex], next[target]] = [next[target], next[cardIndex]]
    return next
  })
}

function updateCards(
  args: CreateAdsArgs,
  adIndex: number,
  change: (cards: unknown[]) => unknown[]
): EditedAds {
  return args.rawAds.map((ad, position) => {
    if (position !== adIndex || !Array.isArray(ad["cards"])) return ad
    return { ...ad, cards: change(ad["cards"]) }
  })
}

/** Sets or removes an ad's main media or its vertical version. */
export function setAdMedia(
  args: CreateAdsArgs,
  index: number,
  slot: MediaSlot,
  value: MediaValue | null
): EditedAds {
  return args.rawAds.map((ad, position) => (position === index ? withValue(ad, slot, value) : ad))
}

/** Swaps a card's media; only video cards keep a thumbnail. */
export function setCardMedia(
  args: CreateAdsArgs,
  adIndex: number,
  cardIndex: number,
  value: MediaValue
): EditedAds {
  return updateCards(args, adIndex, (cards) =>
    cards.map((card, position) => {
      if (position !== cardIndex || !isRecord(card)) return card
      const next = withValue(card, "media", value)
      return value["media_type"] === "video" ? next : withValue(next, "thumbnail", null)
    })
  )
}

/** Adds a card for the media; its headline starts empty for the operator to write. */
export function addCard(args: CreateAdsArgs, adIndex: number, value: MediaValue): EditedAds {
  return updateCards(args, adIndex, (cards) =>
    cards.length < MAX_CARDS ? [...cards, { media: value, headline: "" }] : cards
  )
}

export function removeCard(args: CreateAdsArgs, adIndex: number, cardIndex: number): EditedAds {
  return updateCards(args, adIndex, (cards) =>
    cards.length > MIN_CARDS ? cards.filter((_card, position) => position !== cardIndex) : cards
  )
}

// A null value removes the key, so an override goes back to the shared value.
function withValue(record: Record<string, unknown>, key: string, value: unknown) {
  const rest = Object.fromEntries(Object.entries(record).filter(([candidate]) => candidate !== key))
  return value === null ? rest : { ...rest, [key]: value }
}

export function toggleChange(args: CreateAdsArgs, key: string, on: boolean): string[] | null {
  const next = on
    ? [...new Set([...args.enabledChanges, key])]
    : args.enabledChanges.filter((item) => item !== key)
  return next.length > 0 ? next : null
}
