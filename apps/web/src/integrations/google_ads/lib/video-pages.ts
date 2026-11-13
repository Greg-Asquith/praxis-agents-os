// apps/web/src/integrations/google_ads/lib/video-pages.ts

import { isGoogleAdsUrl } from "@/integrations/google_ads/lib/field-values"

// The server's limit on the pages Google may take videos from.
const MAX_VIDEO_PAGES = 20

export const VIDEO_PAGES_TITLE = "Let Google Find Videos on These Pages"

export const VIDEO_PAGES_HELP =
  "Google looks for videos on pages you list (the site, a YouTube channel, or a social profile) and can add them to this campaign's ads."

// Google's condition for turning this on, which the approver accepts for the advertiser.
export const VIDEO_PAGES_RIGHTS =
  "Listing a page confirms the advertiser owns the rights to its videos and can share them with Google for ads."

/** Reads a list of page addresses; null when it isn't one. */
export function parseVideoPages(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) return null
  return value as string[]
}

/** The pages each once, in the order the server keeps them. */
export function sortedVideoPages(pages: readonly string[]): string[] {
  return [...new Set(pages)].sort()
}

/** The pages in typed or pasted text. An address can hold a comma, so only spaces separate. */
export function videoPagesFromText(text: string): string[] {
  return sortedVideoPages(text.split(/\s+/).filter(Boolean))
}

/** Why the server refuses the pages, or null. */
export function videoPagesProblem(pages: readonly string[]): string | null {
  if (pages.length > MAX_VIDEO_PAGES)
    return `Google takes at most ${String(MAX_VIDEO_PAGES)} video pages here.`
  return pages.some((page) => !isGoogleAdsUrl(page))
    ? "Enter each video page as a full address starting with http:// or https://."
    : null
}
