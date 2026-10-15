// apps/web/src/integrations/meta_ads/components/carousel-cards.tsx

import {
  ArrowDownIcon,
  ArrowUpIcon,
  ChevronRightIcon,
  ImageUpIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react"
import { useId, useState } from "react"

import { fieldOptionLabel } from "@/components/tool-ui/field-options"
import { Button } from "@/components/ui/button"
import { ButtonSelect } from "@/integrations/meta_ads/components/button-select"
import { LabelledInput } from "@/integrations/meta_ads/components/editor-fields"
import {
  CheckMark,
  CheckMessages,
  LengthCounter,
} from "@/integrations/meta_ads/components/field-notes"
import { MediaFrame } from "@/integrations/meta_ads/components/media-frame"
import { MediaPicker } from "@/integrations/meta_ads/components/media-picker"
import {
  cardKeys,
  MAX_CARDS,
  MIN_CARDS,
  RECOMMENDED_LENGTHS,
  type Card,
  type CreateAdsArgs,
} from "@/integrations/meta_ads/lib/create-ads-args"
import { hasError, type AdCheck, type AdRow } from "@/integrations/meta_ads/lib/create-ads-checks"
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
import { cn } from "@/lib/utils"

const MEDIA_TYPES = ["image", "video"] as const

// What the card's closed row flags; the ad's own checks give the full messages.
function cardChecks(card: Card): AdCheck[] {
  const checks: AdCheck[] = []
  if (!card.headline.trim()) {
    checks.push({ level: "error", message: "Write a headline.", field: "cards" })
  }
  for (const [text, limit] of [
    [card.headline, RECOMMENDED_LENGTHS.cardHeadline],
    [card.description ?? "", RECOMMENDED_LENGTHS.cardDescription],
  ] as const) {
    if (text.length > limit) {
      checks.push({ level: "warning", message: "Longer than Meta recommends.", field: "cards" })
    }
  }
  return checks
}

/** Collapsible cards: each opens to its media, text, link, and button, and moves or goes. */
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
  const [openKey, setOpenKey] = useState<string | null>(null)
  const cards = row.ad.cards
  const keys = cardKeys(cards)
  const used = cards.map((card) => card.media.key)
  return (
    <section aria-label={`Cards in ${row.ad.name}`} className="grid min-w-0 gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">Cards</p>
          <p className="text-muted-foreground text-sm">
            {String(cards.length)} of {String(MAX_CARDS)}. Each card needs different media.
          </p>
        </div>
        {cards.length < MAX_CARDS ? (
          <MediaPicker
            accept={MEDIA_TYPES}
            description="Choose an image or video for the new card. Each card needs different media."
            disabled={disabled}
            excluded={used}
            onChoose={(value) => {
              onEdit(addCard(args, row.ad.index, value))
            }}
            title="Add a Card"
          >
            <PlusIcon />
            Add Card
          </MediaPicker>
        ) : null}
      </div>
      <CheckMessages checks={checks} />
      <ol className="divide-y overflow-hidden rounded-lg border">
        {cards.map((card, index) => {
          const key = keys[index] ?? String(index)
          const open = openKey === key
          const flags = cardChecks(card)
          const label = `card ${String(index + 1)} of ${row.ad.name}`
          const fieldId = `${id}-${String(index)}`
          const edit = (field: EditableCardKey, value: string | null) => {
            onEdit(editCard(args, row.ad.index, index, field, value))
          }
          const buttonLabel = fieldOptionLabel(card.callToAction ?? row.callToAction)
          return (
            <li
              key={key}
              aria-label={`Card ${String(index + 1)}`}
              className={cn(open && "bg-muted/40")}
            >
              <div className="flex flex-wrap items-center gap-2 px-3 py-2">
                <button
                  aria-controls={open ? `${fieldId}-body` : undefined}
                  aria-expanded={open}
                  className="focus-visible:ring-ring/50 flex min-h-10 min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-md text-left outline-none focus-visible:ring-3"
                  onClick={() => {
                    setOpenKey(open ? null : key)
                  }}
                  type="button"
                >
                  <ChevronRightIcon
                    aria-hidden="true"
                    className={cn("size-4 shrink-0 transition-transform", open && "rotate-90")}
                  />
                  <MediaFrame
                    className="size-10 shrink-0 rounded-md"
                    media={card.media}
                    shape="square"
                  />
                  <span className="text-sm font-medium whitespace-nowrap">
                    Card {String(index + 1)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm">
                    {card.headline || "No headline"} · {buttonLabel}
                    {card.callToAction ? "" : " (same as ad)"}
                  </span>
                  {flags.length > 0 ? (
                    <CheckMark check={hasError(flags) ? "error" : "warning"} checks={flags} />
                  ) : null}
                </button>
                <div className="flex shrink-0 gap-1">
                  <Button
                    aria-label={`Move ${label} up`}
                    disabled={disabled || index === 0}
                    onClick={() => {
                      onEdit(moveCard(args, row.ad.index, index, -1))
                    }}
                    type="button"
                    variant="ghost"
                  >
                    <ArrowUpIcon />
                    Up
                  </Button>
                  <Button
                    aria-label={`Move ${label} down`}
                    disabled={disabled || index === cards.length - 1}
                    onClick={() => {
                      onEdit(moveCard(args, row.ad.index, index, 1))
                    }}
                    type="button"
                    variant="ghost"
                  >
                    <ArrowDownIcon />
                    Down
                  </Button>
                  <Button
                    aria-label={`Remove ${label}`}
                    disabled={disabled || cards.length <= MIN_CARDS}
                    onClick={() => {
                      onEdit(removeCard(args, row.ad.index, index))
                    }}
                    title={
                      cards.length <= MIN_CARDS
                        ? `A carousel needs at least ${String(MIN_CARDS)} cards`
                        : undefined
                    }
                    type="button"
                    variant="ghost"
                  >
                    <Trash2Icon />
                    Remove
                  </Button>
                </div>
              </div>
              {open ? (
                <div className="grid min-w-0 gap-3 px-3 pt-1 pb-3" id={`${fieldId}-body`}>
                  <div className="flex items-center gap-3">
                    <MediaFrame
                      className="size-24 shrink-0 rounded-md"
                      media={card.media}
                      shape="square"
                    />
                    <MediaPicker
                      accept={MEDIA_TYPES}
                      description="Each card needs different media."
                      disabled={disabled}
                      excluded={used.filter((usedKey) => usedKey !== card.media.key)}
                      onChoose={(value) => {
                        onEdit(setCardMedia(args, row.ad.index, index, value))
                      }}
                      title={`Change the Media on Card ${String(index + 1)}`}
                      triggerLabel={`Change the media on ${label}`}
                    >
                      <ImageUpIcon />
                      Change Media
                    </MediaPicker>
                  </div>
                  <div className="grid gap-3 @xl:grid-cols-2">
                    <LabelledInput
                      accessibleLabel={`Headline for ${label}`}
                      counter={
                        <LengthCounter
                          length={card.headline.length}
                          limit={RECOMMENDED_LENGTHS.cardHeadline}
                        />
                      }
                      disabled={disabled}
                      id={`${fieldId}-headline`}
                      label="Headline"
                      onChange={(value) => {
                        edit("headline", value)
                      }}
                      value={card.headline}
                    />
                    <LabelledInput
                      accessibleLabel={`Description for ${label}`}
                      counter={
                        <LengthCounter
                          length={card.description?.length ?? 0}
                          limit={RECOMMENDED_LENGTHS.cardDescription}
                        />
                      }
                      disabled={disabled}
                      id={`${fieldId}-description`}
                      label="Description"
                      onChange={(value) => {
                        edit("description", blankToNull(value))
                      }}
                      placeholder="Optional"
                      value={card.description ?? ""}
                    />
                    <LabelledInput
                      accessibleLabel={`Link for ${label}`}
                      disabled={disabled}
                      id={`${fieldId}-link`}
                      inputMode="url"
                      label="Link"
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
                </div>
              ) : null}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
