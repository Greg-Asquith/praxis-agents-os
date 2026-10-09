// apps/web/src/integrations/meta_ads/components/ad-preview.tsx

import { GlobeIcon } from "lucide-react"

import { fieldOptionLabel } from "@/components/tool-ui/field-options"
import { MediaFrame } from "@/integrations/meta_ads/components/media-frame"
import { useMetaPicture } from "@/integrations/meta_ads/lib/meta-pictures"
import {
  cardKeys,
  cutOff,
  RECOMMENDED_LENGTHS,
  type PreviewMedia,
} from "@/integrations/meta_ads/lib/create-ads-args"
import { initials } from "@/lib/format"
import { cn } from "@/lib/utils"

export type AdPlacement = "feed" | "stories"

type PreviewCard = {
  media: PreviewMedia
  headline: string
  description: string | null
  callToAction: string
}

export type AdPreviewProps = {
  placement: AdPlacement
  pageName: string
  pageId: string | null
  format: "image" | "video" | "carousel"
  primaryText: string
  headline: string | null
  description: string | null
  callToAction: string
  domain: string | null
  media: PreviewMedia | null
  verticalMedia: PreviewMedia | null
  cards: PreviewCard[]
}

/** A Praxis drawing of the ad from typed values; every string renders as plain text. */
export function AdPreview({ placement, ...props }: AdPreviewProps) {
  return placement === "stories" ? <StoriesPreview {...props} /> : <FeedPreview {...props} />
}

type PlacementPreviewProps = Omit<AdPreviewProps, "placement">

function FeedPreview({
  pageName,
  pageId,
  format,
  primaryText,
  headline,
  description,
  callToAction,
  domain,
  media,
  cards,
}: PlacementPreviewProps) {
  const text = cutOff(primaryText, RECOMMENDED_LENGTHS.primaryText)
  const keys = cardKeys(cards)
  return (
    <figure
      aria-label="Feed preview"
      className="bg-card grid w-full min-w-0 overflow-hidden rounded-xl border shadow-xs"
    >
      <div className="grid gap-2 px-3 pt-3 pb-2">
        <PreviewHeader pageId={pageId} pageName={pageName} />
        {text.shown ? (
          <p className="text-sm leading-snug wrap-anywhere whitespace-pre-line">
            {text.shown}
            {text.hidden ? <span className="text-muted-foreground">… See more</span> : null}
          </p>
        ) : null}
      </div>
      {format === "carousel" ? (
        <div className="flex snap-x gap-2 overflow-x-auto px-3 pb-3">
          {cards.map((card, index) => (
            <div
              key={keys[index]}
              className="grid w-[72%] shrink-0 snap-start overflow-hidden rounded-lg border"
            >
              <MediaFrame media={card.media} shape="square" />
              <LinkBar
                callToAction={card.callToAction}
                description={card.description}
                domain={null}
                headline={cutOff(card.headline, RECOMMENDED_LENGTHS.cardHeadline).shown}
              />
            </div>
          ))}
        </div>
      ) : (
        <>
          <MediaFrame media={media} shape="feed" />
          <LinkBar
            callToAction={callToAction}
            description={description}
            domain={domain}
            headline={headline ? cutOff(headline, RECOMMENDED_LENGTHS.headline).shown : null}
          />
        </>
      )}
    </figure>
  )
}

function LinkBar({
  callToAction,
  description,
  domain,
  headline,
}: {
  callToAction: string
  description: string | null
  domain: string | null
  headline: string | null
}) {
  return (
    <div className="bg-muted/50 flex min-w-0 items-center justify-between gap-3 px-3 py-2">
      <div className="grid min-w-0 gap-0.5">
        {domain ? (
          <p className="text-muted-foreground truncate text-[0.6875rem] tracking-wide uppercase">
            {domain}
          </p>
        ) : null}
        {headline ? (
          <p className="line-clamp-2 text-sm leading-snug font-semibold wrap-anywhere">
            {headline}
          </p>
        ) : null}
        {description ? (
          <p className="text-muted-foreground truncate text-xs">{description}</p>
        ) : null}
      </div>
      <PreviewButton callToAction={callToAction} />
    </div>
  )
}

function StoriesPreview({
  pageName,
  pageId,
  format,
  primaryText,
  callToAction,
  media,
  verticalMedia,
  cards,
}: PlacementPreviewProps) {
  const shown = format === "carousel" ? (cards[0]?.media ?? null) : (verticalMedia ?? media)
  return (
    <figure
      aria-label="Stories and Reels preview"
      className="relative mx-auto grid aspect-[9/16] w-full max-w-60 min-w-0 overflow-hidden rounded-xl bg-neutral-900"
    >
      {/* Without a vertical version, Meta centres the main media on a plain background. */}
      <div className="absolute inset-0 flex items-center justify-center">
        <MediaFrame
          className={cn(verticalMedia && format !== "carousel" && "h-full")}
          media={shown}
          shape={verticalMedia && format !== "carousel" ? "fill" : "feed"}
        />
      </div>
      <div className="absolute inset-x-0 top-0 bg-gradient-to-b from-black/50 to-transparent p-3">
        <PreviewHeader inverted pageId={pageId} pageName={pageName} />
      </div>
      <div className="absolute inset-x-0 bottom-0 grid gap-2 bg-gradient-to-t from-black/60 to-transparent p-3 pt-8">
        <p className="line-clamp-2 text-xs wrap-anywhere text-white">{primaryText}</p>
        <PreviewButton callToAction={callToAction} wide />
      </div>
    </figure>
  )
}

function PreviewHeader({
  pageName,
  pageId,
  inverted = false,
}: {
  pageName: string
  pageId: string | null
  inverted?: boolean
}) {
  const picture = useMetaPicture(pageId ? `page_${pageId}` : null)
  return (
    <div className="flex min-w-0 items-center gap-2">
      {picture.src ? (
        <img alt="" className="size-8 shrink-0 rounded-full object-cover" src={picture.src} />
      ) : (
        <span
          aria-hidden="true"
          className="bg-primary/15 text-primary flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
        >
          {initials(pageName)}
        </span>
      )}
      <span className="grid min-w-0">
        <span className={cn("truncate text-sm font-semibold", inverted && "text-white")}>
          {pageName}
        </span>
        <span
          className={cn(
            "text-muted-foreground flex items-center gap-1 text-xs",
            inverted && "text-white/80"
          )}
        >
          Sponsored <GlobeIcon aria-hidden="true" className="size-3" />
        </span>
      </span>
    </div>
  )
}

function PreviewButton({ callToAction, wide = false }: { callToAction: string; wide?: boolean }) {
  if (callToAction === "NO_BUTTON") return null
  return (
    <span
      className={cn(
        "bg-background shrink-0 rounded-md border px-3 py-1.5 text-center text-xs font-semibold whitespace-nowrap",
        wide && "w-full border-transparent bg-white text-neutral-900"
      )}
    >
      {fieldOptionLabel(callToAction)}
    </span>
  )
}
