// apps/web/src/integrations/meta_ads/components/carousel-cards.tsx

import { ArrowLeftIcon, ArrowRightIcon, ImageUpIcon, PlusIcon, Trash2Icon } from "lucide-react"
import { useId } from "react"

import { fieldOptionLabel } from "@/components/tool-ui/field-options"
import { Button } from "@/components/ui/button"
import { ButtonSelect } from "@/integrations/meta_ads/components/button-select"
import { LabelledInput } from "@/integrations/meta_ads/components/editor-fields"
import { CheckMessages, LengthCounter } from "@/integrations/meta_ads/components/field-notes"
import { MediaFrame } from "@/integrations/meta_ads/components/media-frame"
import { MediaPicker } from "@/integrations/meta_ads/components/media-picker"
import {
  cardKeys,
  MAX_CARDS,
  MIN_CARDS,
  RECOMMENDED_LENGTHS,
  type CreateAdsArgs,
} from "@/integrations/meta_ads/lib/create-ads-args"
import type { AdCheck, AdRow } from "@/integrations/meta_ads/lib/create-ads-checks"
import {
  addCard,
  blankToNull,
  editCard,
  moveCard,
  removeCard,
  setCardMedia,
  type EditableCardKey,
  type EditedAds,
} from "@/integrations/meta_ads/lib/create-ads-edits"

const MEDIA_TYPES = ["image", "video"] as const

/** Edits each card's media, text, link, button, and position, and adds or removes cards. */
export function CarouselCards({
  args,
  row,
  checks,
  disabled,
  onEdit,
}: {
  args: CreateAdsArgs
  row: AdRow
  checks: readonly AdCheck[]
  disabled: boolean
  onEdit: (ads: EditedAds) => void
}) {
  const id = useId()
  const cards = row.ad.cards
  const keys = cardKeys(cards)
  const used = cards.map((card) => card.media.key)
  return (
    <section aria-label={`Cards in ${row.ad.name}`} className="grid min-w-0 gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-medium">Cards</p>
        <p className="text-muted-foreground text-xs">
          {String(cards.length)} of {String(MAX_CARDS)}
        </p>
      </div>
      <CheckMessages checks={checks} />
      <ol className="flex min-w-0 snap-x gap-3 overflow-x-auto pb-2">
        {cards.map((card, index) => {
          const label = `card ${String(index + 1)} of ${row.ad.name}`
          const fieldId = `${id}-${String(index)}`
          const edit = (key: EditableCardKey, value: string | null) => {
            onEdit(editCard(args, row.ad.index, index, key, value))
          }
          return (
            <li
              key={keys[index]}
              aria-label={`Card ${String(index + 1)}`}
              className="bg-card grid w-60 shrink-0 snap-start grid-cols-1 content-start gap-2 overflow-hidden rounded-lg border"
            >
              <div className="relative">
                <MediaFrame media={card.media} shape="square" />
                <span className="absolute top-1.5 right-1.5 flex gap-1">
                  <MediaPicker
                    accept={MEDIA_TYPES}
                    description="Each card needs different media."
                    disabled={disabled}
                    excluded={used.filter((key) => key !== card.media.key)}
                    onChoose={(value) => {
                      onEdit(setCardMedia(args, row.ad.index, index, value))
                    }}
                    size="icon-xs"
                    title={`Change the Media on Card ${String(index + 1)}`}
                    triggerClassName="bg-background/90"
                    triggerLabel={`Change the media on ${label}`}
                  >
                    <ImageUpIcon />
                  </MediaPicker>
                  <Button
                    aria-label={`Remove ${label}`}
                    className="bg-background/90"
                    disabled={disabled || cards.length <= MIN_CARDS}
                    onClick={() => {
                      onEdit(removeCard(args, row.ad.index, index))
                    }}
                    size="icon-xs"
                    title={
                      cards.length <= MIN_CARDS
                        ? `A carousel needs at least ${String(MIN_CARDS)} cards`
                        : undefined
                    }
                    type="button"
                    variant="outline"
                  >
                    <Trash2Icon />
                  </Button>
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 px-1.5">
                <Button
                  aria-label={`Move ${label} left`}
                  disabled={disabled || index === 0}
                  onClick={() => {
                    onEdit(moveCard(args, row.ad.index, index, -1))
                  }}
                  size="icon-xs"
                  type="button"
                  variant="ghost"
                >
                  <ArrowLeftIcon />
                </Button>
                <span className="text-muted-foreground text-xs font-medium">
                  Card {String(index + 1)}
                </span>
                <Button
                  aria-label={`Move ${label} right`}
                  disabled={disabled || index === cards.length - 1}
                  onClick={() => {
                    onEdit(moveCard(args, row.ad.index, index, 1))
                  }}
                  size="icon-xs"
                  type="button"
                  variant="ghost"
                >
                  <ArrowRightIcon />
                </Button>
              </div>
              <div className="grid min-w-0 gap-2 px-2.5 pb-2.5">
                <LabelledInput
                  counter={
                    <LengthCounter
                      length={card.headline.length}
                      limit={RECOMMENDED_LENGTHS.cardHeadline}
                    />
                  }
                  counterBelow
                  disabled={disabled}
                  id={`${fieldId}-headline`}
                  label="Headline"
                  accessibleLabel={`Headline for ${label}`}
                  onChange={(value) => {
                    edit("headline", value)
                  }}
                  value={card.headline}
                />
                <LabelledInput
                  counter={
                    <LengthCounter
                      length={card.description?.length ?? 0}
                      limit={RECOMMENDED_LENGTHS.cardDescription}
                    />
                  }
                  counterBelow
                  disabled={disabled}
                  id={`${fieldId}-description`}
                  label="Description"
                  accessibleLabel={`Description for ${label}`}
                  onChange={(value) => {
                    edit("description", blankToNull(value))
                  }}
                  placeholder="Optional"
                  value={card.description ?? ""}
                />
                <LabelledInput
                  disabled={disabled}
                  id={`${fieldId}-link`}
                  inputMode="url"
                  label="Link"
                  accessibleLabel={`Link for ${label}`}
                  onChange={(value) => {
                    edit("link", blankToNull(value))
                  }}
                  placeholder={row.link ?? undefined}
                  value={card.link ?? ""}
                />
                <ButtonSelect
                  allowed={row.allowedButtons}
                  disabled={disabled}
                  fallbackLabel={`Same as Ad (${fieldOptionLabel(row.callToAction)})`}
                  id={`${fieldId}-button`}
                  label={`Button for ${label}`}
                  onChange={(value) => {
                    edit("call_to_action", value)
                  }}
                  value={card.callToAction}
                />
              </div>
            </li>
          )
        })}
        {cards.length < MAX_CARDS ? (
          <li className="flex w-40 shrink-0 snap-start items-start">
            <MediaPicker
              accept={MEDIA_TYPES}
              description="Choose an image or video for the new card. Each card needs different media."
              disabled={disabled}
              excluded={used}
              onChoose={(value) => {
                onEdit(addCard(args, row.ad.index, value))
              }}
              title="Add a Card"
              triggerClassName="aspect-square h-auto w-full flex-col gap-1 border-dashed"
            >
              <PlusIcon />
              Add Card
            </MediaPicker>
          </li>
        ) : null}
      </ol>
    </section>
  )
}
