// apps/web/src/integrations/google_ads/components/search-ad-preview.tsx

import { EllipsisVerticalIcon } from "lucide-react"

import {
  DESCRIPTION_PINS,
  HEADLINE_PINS,
  previewAssets,
  previewSite,
  type AdCopy,
} from "@/integrations/google_ads/lib/create-ads"

/** The ad as a Google search result, in Google's own type and colours: three headlines and two descriptions. */
export function SearchAdPreview({ ad }: { ad: AdCopy }) {
  const headlines = previewAssets(ad.headlines, HEADLINE_PINS)
  const descriptions = previewAssets(ad.descriptions, DESCRIPTION_PINS)
  const site = previewSite(ad)
  return (
    <figure aria-label="Search result preview" className="grid min-w-0 gap-1.5">
      <div className="min-w-0 rounded-lg border bg-white px-4 py-3 font-[Arial,sans-serif] dark:bg-[#1f1f1f]">
        <p className="mb-2 text-sm font-bold text-[#1f1f1f] dark:text-[#e3e3e3]">Sponsored</p>
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden="true"
            className="flex size-7 shrink-0 items-center justify-center rounded-full border border-[#dadce0] bg-[#f1f3f4] text-sm font-medium text-[#4d5156] uppercase dark:border-[#3c4043] dark:bg-[#303134] dark:text-[#bdc1c6]"
          >
            {site.name.charAt(0)}
          </span>
          <span className="grid min-w-0 leading-tight">
            <span className="truncate text-sm text-[#202124] dark:text-[#dadce0]">{site.name}</span>
            <span className="flex min-w-0 items-center gap-1 text-xs text-[#4d5156] dark:text-[#bdc1c6]">
              <span className="truncate">{site.url}</span>
              <EllipsisVerticalIcon aria-hidden="true" className="size-3.5 shrink-0" />
            </span>
          </span>
        </div>
        <p className="mt-1.5 text-xl leading-snug wrap-anywhere text-[#1a0dab] dark:text-[#99c3ff]">
          {headlines.join(" | ") || "Add headlines to see the preview"}
        </p>
        <p className="mt-1 text-sm leading-relaxed wrap-anywhere text-[#474747] dark:text-[#bfbfbf]">
          {descriptions.join(" ")}
        </p>
      </div>
      <figcaption className="text-muted-foreground text-xs">
        Google mixes headlines and descriptions, so the ad can show other combinations.
      </figcaption>
    </figure>
  )
}
