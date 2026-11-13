// apps/web/src/integrations/google_ads/components/performance-max-settings.tsx

import { useState } from "react"

import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  Chip,
  ChoiceCards,
  FormField,
  SelectField,
  SwitchField,
  TextField,
} from "@/integrations/ads/components/controls"
import { EntitySearch } from "@/integrations/ads/components/entity-search"
import { ImageTiles } from "@/integrations/google_ads/components/image-tiles"
import {
  LOGO_TYPES,
  logoShapeFor,
  type DraftPerformanceMax,
  type PerformanceMaxChecks,
} from "@/integrations/google_ads/lib/performance-max"
import {
  VIDEO_PAGES_HELP,
  VIDEO_PAGES_RIGHTS,
  VIDEO_PAGES_TITLE,
  sortedVideoPages,
  videoPagesFromText,
} from "@/integrations/google_ads/lib/video-pages"

const TOOL_NAME = "google_ads_create_campaign"

type Edit = (patch: Partial<DraftPerformanceMax>) => void

/** Which conversions the campaign bids for: the account's goals, or its own choice of them. */
export function GoalsFields({
  checks,
  disabled,
  fields,
  onEdit,
}: {
  checks: PerformanceMaxChecks | null
  disabled: boolean
  fields: DraftPerformanceMax
  onEdit: Edit
}) {
  const goals = checks?.accountGoals ?? []
  const chosen = fields.conversionGoals
  const isChosen = (category: string, origin: string) =>
    chosen?.some((goal) => goal.category === category && goal.origin === origin) ?? false
  return (
    <div className="grid gap-3">
      <ChoiceCards
        ariaLabel="Conversion goals"
        disabled={disabled}
        onChange={(value) => {
          onEdit({
            conversionGoals:
              value === "account"
                ? null
                : goals
                    .filter((goal) => goal.biddable)
                    .map(({ category, origin }) => ({ category, origin })),
          })
        }}
        options={[
          {
            value: "account",
            label: "Use Account Goals",
            description: "Bid for the goals the account counts for bidding.",
          },
          {
            value: "campaign",
            label: "Choose for This Campaign",
            description: "Bid only for the goals you tick here.",
          },
        ]}
        value={chosen === null ? "account" : "campaign"}
      />
      {goals.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          Google hasn't listed the account's goals yet.
        </p>
      ) : (
        <ul className="grid gap-1.5">
          {goals.map((goal) => {
            const key = `${goal.category}~${goal.origin}`
            const checked = chosen === null ? goal.biddable : isChosen(goal.category, goal.origin)
            return (
              <li key={key} className="flex items-center gap-2 text-sm">
                <Checkbox
                  aria-label={goal.name}
                  checked={checked}
                  disabled={disabled || chosen === null}
                  onCheckedChange={(next) => {
                    const rest = (chosen ?? []).filter(
                      (item) => item.category !== goal.category || item.origin !== goal.origin
                    )
                    onEdit({
                      conversionGoals: next
                        ? [...rest, { category: goal.category, origin: goal.origin }]
                        : rest,
                    })
                  }}
                />
                <span>{goal.name}</span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

/** The business name and logos Google shows across the campaign's ads. */
export function BrandFields({
  checks,
  disabled,
  fields,
  onEdit,
}: {
  checks: PerformanceMaxChecks | null
  disabled: boolean
  fields: DraftPerformanceMax
  onEdit: Edit
}) {
  return (
    <div className="grid min-w-0 gap-3">
      <TextField
        disabled={disabled}
        label="Business Name (Up to 25 Characters)"
        onChange={(businessName) => {
          onEdit({ businessName })
        }}
        value={fields.businessName}
      />
      <div className="grid min-w-0 gap-1.5">
        <p className="text-sm font-medium">Logos</p>
        <ImageTiles
          addLabel="Add Logo"
          checks={checks}
          disabled={disabled}
          fieldKey="campaign"
          images={fields.logos}
          onChange={(logos) => {
            onEdit({ logos })
          }}
          shapeFor={logoShapeFor}
          shapes={LOGO_TYPES}
          toolName={TOOL_NAME}
        />
      </div>
      <p className="text-muted-foreground text-xs">
        Brand guidelines are on, so the name and logos apply to every asset group.
      </p>
    </div>
  )
}

/** The languages the campaign shows ads in; none means every language. */
export function LanguageFields({
  checks,
  disabled,
  fields,
  onEdit,
}: {
  checks: PerformanceMaxChecks | null
  disabled: boolean
  fields: DraftPerformanceMax
  onEdit: Edit
}) {
  const taken = new Set(fields.languages.map((item) => item.key))
  return (
    <div className="grid min-w-0 gap-1.5">
      <p className="text-sm font-medium">
        Languages{" "}
        <span className="text-muted-foreground font-normal">
          {fields.languages.length === 0 ? "Every language" : String(fields.languages.length)}
        </span>
      </p>
      {fields.languages.length > 0 ? (
        <div className="flex min-w-0 flex-wrap gap-1.5">
          {fields.languages.map((language) => (
            <Chip
              key={language.key}
              disabled={disabled}
              label={checks?.languageNames.get(language.key) ?? (language.name || language.key)}
              onRemove={() => {
                onEdit({ languages: fields.languages.filter((item) => item.key !== language.key) })
              }}
            />
          ))}
        </div>
      ) : null}
      <EntitySearch
        disabled={disabled}
        entityKind="google_ads_language"
        fieldKey="campaign"
        isTaken={(choice) => taken.has(String(choice.value["key"]))}
        label="Search for a language"
        onChoose={(choice) => {
          const key = choice.value["key"]
          if (typeof key === "string" && /^\d+$/.test(key) && !taken.has(key))
            onEdit({ languages: [...fields.languages, { key, name: choice.label }] })
        }}
        placeholder="Search languages"
        toolName={TOOL_NAME}
      />
    </div>
  )
}

/** A switch, off unless pages are listed, that reveals the pages Google may take videos from. */
export function VideoPagesField({
  disabled,
  onChange,
  pages,
}: {
  disabled: boolean
  onChange: (pages: string[]) => void
  pages: readonly string[]
}) {
  // On with no pages yet sends nothing, so Google stays off until a page is added.
  const [open, setOpen] = useState(pages.length > 0)
  // Typing stays here until Enter or leaving the field, so a pasted list is added whole.
  const [draft, setDraft] = useState("")
  const add = () => {
    const added = videoPagesFromText(draft)
    setDraft("")
    if (added.length > 0) onChange(sortedVideoPages([...pages, ...added]))
  }
  const on = open || pages.length > 0
  return (
    <div className="grid min-w-0 gap-3">
      <SwitchField
        checked={on}
        description={VIDEO_PAGES_HELP}
        disabled={disabled}
        label={VIDEO_PAGES_TITLE}
        onChange={(next) => {
          setOpen(next)
          setDraft("")
          if (!next && pages.length > 0) onChange([])
        }}
      />
      {on ? (
        <FormField label="Pages">
          {(id) => (
            <>
              {pages.length > 0 ? (
                <div className="flex min-w-0 flex-wrap gap-1.5">
                  {pages.map((page) => (
                    <Chip
                      key={page}
                      disabled={disabled}
                      label={page}
                      onRemove={() => {
                        onChange(pages.filter((item) => item !== page))
                      }}
                    />
                  ))}
                </div>
              ) : null}
              <Input
                className="text-sm"
                disabled={disabled}
                id={id}
                onBlur={add}
                onChange={(event) => {
                  setDraft(event.currentTarget.value)
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault()
                    add()
                  }
                }}
                placeholder="https://example.com/videos"
                value={draft}
              />
              <p className="text-muted-foreground text-xs">
                {pages.length > 0 ? VIDEO_PAGES_RIGHTS : "Add a page to turn this on."}
              </p>
            </>
          )}
        </FormField>
      ) : null}
    </div>
  )
}

/** Final URL expansion and the retail product feed, under More Settings. */
export function PerformanceMaxMoreFields({
  checks,
  disabled,
  fields,
  onEdit,
}: {
  checks: PerformanceMaxChecks | null
  disabled: boolean
  fields: DraftPerformanceMax
  onEdit: Edit
}) {
  const merchant = fields.merchant
  const linked = checks?.merchantIds ?? []
  return (
    <div className="grid min-w-0 gap-3">
      <SwitchField
        checked={fields.finalUrlExpansion}
        description="Let Google send people to other pages on the site when they're likely to convert, and write text to match."
        disabled={disabled}
        label="Final URL Expansion"
        onChange={(finalUrlExpansion) => {
          onEdit({ finalUrlExpansion })
        }}
      />
      <SwitchField
        checked={merchant !== null}
        description="Show products from a Merchant Center account linked to this account."
        disabled={disabled}
        label="Product Feed"
        onChange={(on) => {
          onEdit({ merchant: on ? { feedLabel: "", merchantId: linked[0] ?? "" } : null })
        }}
      />
      {merchant ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {linked.length > 0 ? (
            <SelectField
              disabled={disabled}
              label="Merchant Center Account"
              onChange={(merchantId) => {
                onEdit({ merchant: { ...merchant, merchantId } })
              }}
              options={linked.map((id) => ({ value: id, label: id }))}
              value={merchant.merchantId || null}
            />
          ) : (
            <TextField
              disabled={disabled}
              label="Merchant Center Account ID"
              onChange={(merchantId) => {
                onEdit({ merchant: { ...merchant, merchantId: merchantId.trim() } })
              }}
              value={merchant.merchantId}
            />
          )}
          <TextField
            disabled={disabled}
            label="Feed Label (Optional)"
            onChange={(feedLabel) => {
              onEdit({ merchant: { ...merchant, feedLabel } })
            }}
            value={merchant.feedLabel}
          />
        </div>
      ) : null}
    </div>
  )
}
