// apps/web/src/integrations/meta_ads/components/ad-editor.tsx

import { ImageUpIcon, PencilIcon, PlusIcon, XIcon } from "lucide-react"
import { useId, useState } from "react"

import { fieldLabelClass, fieldWellClass } from "@/components/tool-ui/field-styles"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { AdPreview, type AdPlacement } from "@/integrations/meta_ads/components/ad-preview"
import { CarouselCards } from "@/integrations/meta_ads/components/carousel-cards"
import { DeliveryOverrides } from "@/integrations/meta_ads/components/delivery-overrides"
import { EditorField, LabelledInput } from "@/integrations/meta_ads/components/editor-fields"
import {
  CheckMark,
  CheckMessages,
  LengthCounter,
} from "@/integrations/meta_ads/components/field-notes"
import { MediaPicker } from "@/integrations/meta_ads/components/media-picker"
import {
  adSetName,
  FORMAT_LABELS,
  RECOMMENDED_LENGTHS,
  type CreateAdsArgs,
} from "@/integrations/meta_ads/lib/create-ads-args"
import {
  checksFor,
  hasError,
  type AdCheck,
  type AdRow,
  type CheckField,
} from "@/integrations/meta_ads/lib/create-ads-checks"
import {
  blankToNull,
  editAd,
  setAdMedia,
  type EditableAdKey,
  type EditedAds,
} from "@/integrations/meta_ads/lib/create-ads-edits"
import { titleCaseToken, urlDomain } from "@/lib/format"
import { cn } from "@/lib/utils"

/** One ad: a Praxis preview beside the text it sends, with checks shown where they apply. */
export function AdEditor({
  args,
  count,
  row,
  disabled,
  onEdit,
}: {
  args: CreateAdsArgs
  count: number
  row: AdRow
  disabled: boolean
  onEdit: (ads: EditedAds) => void
}) {
  const id = useId()
  const [placement, setPlacement] = useState<AdPlacement>("feed")
  const { ad } = row
  const edit = (key: EditableAdKey, value: string | null) => {
    onEdit(editAd(args, ad.index, key, value))
  }
  const shownFields = new Set<CheckField>([
    "name",
    "primary_text",
    "link",
    "call_to_action",
    "url_tags",
    "media",
    ...(ad.format === "carousel" ? (["cards"] as const) : (["headline", "description"] as const)),
  ])
  // A check for a field this format doesn't show still needs to be seen.
  const unplaced = row.checks.filter((check) => !shownFields.has(check.field))
  return (
    <div className="@container grid min-w-0 gap-3">
      <AdHeading
        args={args}
        checks={checksFor(row, "name")}
        count={count}
        disabled={disabled}
        id={`${id}-name`}
        onRename={(value) => {
          edit("name", value)
        }}
        row={row}
      />
      <div className="grid min-w-0 gap-4 @xl:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
        <div className="grid min-w-0 content-start gap-2">
          <Tabs
            onValueChange={(value) => {
              setPlacement(value === "stories" ? "stories" : "feed")
            }}
            value={placement}
          >
            <TabsList aria-label={`Preview placement for ${ad.name}`} className="w-full">
              <TabsTrigger value="feed">Feed</TabsTrigger>
              <TabsTrigger value="stories">Stories and Reels</TabsTrigger>
            </TabsList>
          </Tabs>
          <AdPreview
            callToAction={row.callToAction}
            cards={ad.cards.map((card) => ({
              media: card.media,
              headline: card.headline,
              description: card.description,
              callToAction: card.callToAction ?? row.callToAction,
            }))}
            description={ad.description}
            domain={urlDomain(row.link)}
            format={ad.format}
            headline={ad.headline}
            media={ad.media}
            pageId={args.pageId}
            pageName={args.pageName}
            placement={placement}
            primaryText={ad.primaryText}
            verticalMedia={ad.verticalMedia}
          />
          {placement === "stories" && ad.format !== "carousel" && !ad.verticalMedia ? (
            <p className="text-muted-foreground text-xs">
              No vertical version, so Meta fits the main {ad.format} into Stories and Reels like
              this.
            </p>
          ) : null}
          {ad.format !== "carousel" ? (
            <MediaActions args={args} disabled={disabled} onEdit={onEdit} row={row} />
          ) : null}
          <CheckMessages checks={checksFor(row, "media")} />
          <p className="text-muted-foreground text-xs">
            A close preview. Meta&apos;s own may differ slightly by placement.
          </p>
        </div>
        <div className="grid min-w-0 content-start gap-3">
          <CheckMessages checks={unplaced} />
          <EditorField
            checks={checksFor(row, "primary_text")}
            counter={
              <LengthCounter
                length={ad.primaryText.length}
                limit={RECOMMENDED_LENGTHS.primaryText}
              />
            }
            id={`${id}-primary`}
            label="Primary Text"
          >
            <Textarea
              aria-invalid={hasError(checksFor(row, "primary_text"))}
              className="min-h-16 text-sm"
              disabled={disabled}
              id={`${id}-primary`}
              onChange={(event) => {
                edit("primary_text", event.currentTarget.value)
              }}
              value={ad.primaryText}
            />
          </EditorField>
          {ad.format !== "carousel" ? (
            <>
              <LabelledInput
                checks={checksFor(row, "headline")}
                counter={
                  <LengthCounter
                    length={ad.headline?.length ?? 0}
                    limit={RECOMMENDED_LENGTHS.headline}
                  />
                }
                disabled={disabled}
                id={`${id}-headline`}
                label="Headline"
                onChange={(value) => {
                  edit("headline", value)
                }}
                value={ad.headline ?? ""}
              />
              <LabelledInput
                checks={checksFor(row, "description")}
                counter={
                  <LengthCounter
                    length={ad.description?.length ?? 0}
                    limit={RECOMMENDED_LENGTHS.description}
                  />
                }
                disabled={disabled}
                id={`${id}-description`}
                label="Description"
                onChange={(value) => {
                  edit("description", blankToNull(value))
                }}
                placeholder="Optional"
                value={ad.description ?? ""}
              />
            </>
          ) : null}
          {ad.disclaimer ? (
            <div className="grid gap-0.5 text-sm">
              <p className={fieldLabelClass}>{titleCaseToken(ad.disclaimer.type, "Disclaimer")}</p>
              <p className="wrap-anywhere whitespace-pre-line">{ad.disclaimer.text}</p>
              {ad.disclaimer.url ? (
                <p className="text-muted-foreground text-xs wrap-anywhere">{ad.disclaimer.url}</p>
              ) : null}
            </div>
          ) : null}
          <DeliveryOverrides args={args} disabled={disabled} id={id} onEdit={onEdit} row={row} />
        </div>
      </div>
      {ad.format === "carousel" ? (
        <CarouselCards
          args={args}
          checks={checksFor(row, "cards")}
          disabled={disabled}
          onEdit={onEdit}
          row={row}
        />
      ) : null}
    </div>
  )
}

/** Changes an image or video ad's media, and adds, changes, or removes its vertical version. */
function MediaActions({
  args,
  disabled,
  onEdit,
  row,
}: {
  args: CreateAdsArgs
  disabled: boolean
  onEdit: (ads: EditedAds) => void
  row: AdRow
}) {
  const { ad } = row
  const kind = ad.format === "video" ? "video" : "image"
  const noun = FORMAT_LABELS[ad.format]
  const accept = [kind] as const
  return (
    <div className="flex flex-wrap items-center gap-2">
      <MediaPicker
        accept={accept}
        description="Shown in Feed, and in Stories and Reels unless the ad has a vertical version."
        disabled={disabled}
        onChoose={(value) => {
          onEdit(setAdMedia(args, ad.index, "media", value))
        }}
        title={`Change the ${noun}`}
      >
        <ImageUpIcon />
        Change {noun}
      </MediaPicker>
      <MediaPicker
        accept={accept}
        description="A 9:16 version for Stories and Reels, so Meta doesn't crop the main one."
        disabled={disabled}
        onChoose={(value) => {
          onEdit(setAdMedia(args, ad.index, "vertical_media", value))
        }}
        title={ad.verticalMedia ? "Change the Vertical Version" : "Add a Vertical Version"}
      >
        {ad.verticalMedia ? <ImageUpIcon /> : <PlusIcon />}
        {ad.verticalMedia ? "Change Vertical Version" : "Add Vertical Version"}
      </MediaPicker>
      {ad.verticalMedia ? (
        <Button
          disabled={disabled}
          onClick={() => {
            onEdit(setAdMedia(args, ad.index, "vertical_media", null))
          }}
          size="sm"
          type="button"
          variant="ghost"
        >
          <XIcon />
          Remove Vertical Version
        </Button>
      ) : null}
    </div>
  )
}

/** The ad's name, edited in place, with where it goes and how it checks out. */
function AdHeading({
  args,
  checks,
  count,
  disabled,
  id,
  onRename,
  row,
}: {
  args: CreateAdsArgs
  checks: AdCheck[]
  count: number
  disabled: boolean
  id: string
  onRename: (value: string) => void
  row: AdRow
}) {
  const adSets = row.ad.adSetIds.map((adSetId) => adSetName(args, adSetId))
  return (
    <div className="grid min-w-0 gap-1">
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          {count > 1 ? (
            <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
              {String(row.ad.index + 1)}/{String(count)}
            </span>
          ) : null}
          <div className="relative min-w-0 flex-1">
            <Input
              aria-invalid={hasError(checks)}
              aria-label="Ad name, shown only in Ads Manager"
              className={cn(fieldWellClass, "h-8 pr-8 font-medium")}
              disabled={disabled}
              id={id}
              onChange={(event) => {
                onRename(event.currentTarget.value)
              }}
              value={row.ad.name}
            />
            <PencilIcon
              aria-hidden="true"
              className="text-muted-foreground pointer-events-none absolute top-1/2 right-2.5 size-3.5 -translate-y-1/2"
            />
          </div>
        </div>
        <CheckMark check={row.check} checks={row.checks} />
      </div>
      <p className="text-muted-foreground text-xs wrap-anywhere">
        {FORMAT_LABELS[row.ad.format]}
        {row.ad.verticalMedia ? " with a vertical version" : ""} in {adSets.join(", ")}
      </p>
      <CheckMessages checks={checks} />
    </div>
  )
}
