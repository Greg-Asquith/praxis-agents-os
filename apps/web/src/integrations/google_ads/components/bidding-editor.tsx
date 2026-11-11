// apps/web/src/integrations/google_ads/components/bidding-editor.tsx

import { InfoIcon, PencilIcon, XIcon } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { CommittedInput } from "@/integrations/ads/components/committed-input"
import { FormField } from "@/integrations/ads/components/controls"
import { EntityPicker } from "@/integrations/ads/components/entity-picker"
import {
  biddingDetail,
  biddingName,
  biddingSentence,
  canonicalMoney,
  moneyInput,
  parseBidding,
  PORTFOLIO,
  portfolioLabel,
  resolvedBidding,
  roasPercent,
  shownBidding,
  STANDARD_STRATEGIES,
  strategyLabel,
  TARGET_LABELS,
  targetFix,
  TARGETS,
  type Bidding,
  type BiddingContext,
} from "@/integrations/google_ads/lib/campaign-bidding"
import { PAGE_LOCATIONS } from "@/integrations/google_ads/lib/create-campaign"
import { parseGoogleAdsMoney } from "@/integrations/google_ads/lib/field-values"
import {
  isBidding,
  valueText,
  type CampaignRow,
} from "@/integrations/google_ads/lib/update-campaigns"
import { currencySymbol } from "@/lib/format"
import { cn } from "@/lib/utils"

const TOOL_NAME = "google_ads_update_campaigns"
// Short labels for page position, so three fields fit on one line.
const PAGE_POSITIONS = {
  ABSOLUTE_TOP_OF_PAGE: "Very top",
  ANYWHERE_ON_PAGE: "Anywhere",
  TOP_OF_PAGE: "Top of the page",
} as const

type BiddingProps = {
  context: BiddingContext
  disabled: boolean
  onChange: (value: Bidding) => void
  row: CampaignRow
}

function rowBidding(row: CampaignRow): { value: Bidding; was: Bidding | undefined } | null {
  if (!isBidding(row.value)) return null
  return { value: row.value, was: isBidding(row.was) ? row.was : undefined }
}

/** One campaign's bidding change: what it is now beside the new strategy and its targets. */
export function BiddingChange({
  context,
  disabled,
  onCancel,
  onChange,
  onUndo,
  row,
}: BiddingProps & { onCancel: () => void; onUndo: () => void }) {
  const bidding = rowBidding(row)
  if (bidding === null) return null
  const { value, was } = bidding
  return (
    <section aria-label="Bidding" className="overflow-hidden rounded-lg border">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-2">
        <h4 className="text-sm font-medium">Bidding</h4>
        {row.cancelled ? (
          <Button disabled={disabled} onClick={onUndo} size="sm" type="button" variant="ghost">
            Undo
          </Button>
        ) : (
          <Button
            aria-label="Cancel This Change"
            disabled={disabled}
            onClick={onCancel}
            size="icon-xs"
            title="Cancel This Change"
            type="button"
            variant="ghost"
          >
            <XIcon />
          </Button>
        )}
      </div>
      {row.cancelled ? (
        <p className="text-muted-foreground px-4 py-3 text-sm line-through">
          {valueText("bidding", was, context)} → {valueText("bidding", value, context)}
        </p>
      ) : (
        <div className="grid sm:grid-cols-[11rem_minmax(0,1fr)]">
          <div className="bg-muted/40 grid content-start gap-1 border-b p-4 sm:border-r sm:border-b-0">
            <p className="text-muted-foreground text-xs font-medium">Now</p>
            {was ? (
              <>
                <p className="text-sm font-medium">{biddingName(was, context)}</p>
                <p className="text-muted-foreground text-sm">{biddingDetail(was, context)}</p>
              </>
            ) : (
              <p className="text-muted-foreground text-sm">Couldn't read</p>
            )}
          </div>
          <div className="grid min-w-0 content-start gap-3 p-4">
            <ProblemWithFix
              disabled={disabled}
              onChange={onChange}
              problem={row.problem}
              value={value}
              was={was}
            />
            <BiddingFields
              context={context}
              disabled={disabled}
              onChange={onChange}
              value={value}
              was={was}
            />
            {row.problem === null ? <Readback context={context} row={row} /> : null}
            <Notes notes={row.notes} />
          </div>
        </div>
      )}
    </section>
  )
}

/** A table cell: the change in one line, with its full editor behind the edit button. */
export function BiddingCell({ context, disabled, onChange, row }: BiddingProps) {
  const [open, setOpen] = useState(false)
  const bidding = rowBidding(row)
  if (bidding === null) return null
  const { value, was } = bidding
  if (row.cancelled)
    return (
      <span className="text-muted-foreground text-sm line-through">
        {valueText("bidding", was, context)} → {valueText("bidding", value, context)}
      </span>
    )
  return (
    <div className="grid min-w-0 gap-1.5 text-sm">
      <div className="flex min-w-0 items-start gap-2">
        <p className="min-w-0 flex-1 wrap-anywhere whitespace-normal">
          <span className="text-muted-foreground">{valueText("bidding", was, context)} → </span>
          {valueText("bidding", value, context)}
        </p>
        {row.unchanged ? <Badge variant="secondary">Already Set</Badge> : null}
        <Button
          aria-expanded={open}
          aria-label={`${open ? "Close" : "Edit"} bidding for ${row.campaignName}`}
          className={cn(open && "bg-muted")}
          disabled={disabled}
          onClick={(event) => {
            event.stopPropagation()
            setOpen(!open)
          }}
          size="icon-xs"
          type="button"
          variant="ghost"
        >
          <PencilIcon />
        </Button>
      </div>
      {row.notes.length > 0 ? (
        <p className="text-muted-foreground text-xs whitespace-normal">{row.notes.join(" · ")}</p>
      ) : null}
      {open ? (
        <div className="bg-background grid gap-3 rounded-lg border p-3 whitespace-normal">
          <ProblemWithFix
            disabled={disabled}
            onChange={onChange}
            problem={null}
            value={value}
            was={was}
          />
          <BiddingFields
            compact
            context={context}
            disabled={disabled}
            onChange={onChange}
            value={value}
            was={was}
          />
        </div>
      ) : null}
    </div>
  )
}

/** The row's problem, with a one-click fix when a target needs another strategy. */
function ProblemWithFix({
  disabled,
  onChange,
  problem,
  value,
  was,
}: {
  disabled: boolean
  onChange: (value: Bidding) => void
  problem: string | null
  value: Bidding
  was: Bidding | undefined
}) {
  const fix = targetFix(value, was)
  if (problem === null && fix === null) return null
  return (
    <div
      className="border-destructive/30 bg-destructive/5 grid gap-2 rounded-lg border px-3 py-2.5"
      role="alert"
    >
      {problem ? <p className="text-destructive text-sm">{problem}</p> : null}
      {fix ? (
        <Button
          className="w-fit"
          disabled={disabled}
          onClick={() => {
            onChange(fix)
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          Switch to {strategyLabel(fix.strategy)}
        </Button>
      ) : null}
    </div>
  )
}

/** Says back what the chosen bidding does, and whether learning carries on. */
function Readback({ context, row }: { context: BiddingContext; row: CampaignRow }) {
  const bidding = rowBidding(row)
  if (bidding === null) return null
  const { bidding: result } = resolvedBidding(bidding.value, bidding.was)
  return (
    <div className="flex flex-wrap items-center gap-2">
      <p className="text-muted-foreground min-w-0 flex-1 text-sm">
        {row.learning || row.unchanged ? "" : "Same strategy, so learning carries on. "}
        {biddingSentence(result, context)}
      </p>
      {row.unchanged ? <Badge variant="secondary">Already Set</Badge> : null}
    </div>
  )
}

function Notes({ notes }: { notes: readonly string[] }) {
  if (notes.length === 0) return null
  return (
    <ul className="grid gap-1.5 border-t pt-3">
      {notes.map((note) => (
        <li key={note} className="text-muted-foreground flex gap-2 text-sm">
          <InfoIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {note}
        </li>
      ))}
    </ul>
  )
}

/** The strategy choice and the targets that strategy takes, each with its own label. */
function BiddingFields({
  compact = false,
  context,
  disabled,
  onChange,
  value,
  was,
}: {
  compact?: boolean
  context: BiddingContext
  disabled: boolean
  onChange: (value: Bidding) => void
  value: Bidding
  was: Bidding | undefined
}) {
  // A portfolio needs a strategy chosen before the request can name it.
  const [choosingPortfolio, setChoosingPortfolio] = useState(false)
  const shown = shownBidding(value, was)
  const strategy = choosingPortfolio ? PORTFOLIO : shown.strategy
  const options = [...new Set<string>([...STANDARD_STRATEGIES, PORTFOLIO, shown.strategy])]
  const edit = (patch: Partial<Bidding>) => {
    const next = parseBidding({ ...value, ...patch })
    if (next) onChange(next)
  }
  const choose = (next: string) => {
    if (next === strategy) return
    setChoosingPortfolio(next === PORTFOLIO)
    if (next === PORTFOLIO) return
    const location = next === "TARGET_IMPRESSION_SHARE" ? (value.location ?? "TOP_OF_PAGE") : null
    edit({ strategy: next, location })
  }
  return (
    <div className="grid gap-3">
      <FormField label={strategy === was?.strategy ? "Strategy" : "New Strategy"}>
        {(id) => (
          <Select<string>
            disabled={disabled}
            onValueChange={(next) => {
              if (next !== null) choose(next)
            }}
            value={strategy}
          >
            <SelectTrigger className="w-full" id={id}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="start">
              <SelectGroup>
                {options.map((option) => (
                  <SelectItem key={option} label={strategyLabel(option)} value={option}>
                    {strategyLabel(option)}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        )}
      </FormField>
      {strategy === PORTFOLIO ? (
        <EntityPicker
          currentLabel={value.strategy === PORTFOLIO ? portfolioLabel(value, context) : null}
          disabled={disabled}
          entityKind="google_ads_bidding_strategy"
          fieldKey="changes"
          label="Portfolio Strategy"
          onChoose={(reference) => {
            const next = parseBidding({ strategy: PORTFOLIO, portfolio: reference })
            if (next) {
              setChoosingPortfolio(false)
              onChange(next)
            }
          }}
          toolName={TOOL_NAME}
        />
      ) : (
        <TargetFields
          compact={compact}
          context={context}
          disabled={disabled}
          invalid={targetFix(value, was) !== null}
          onEdit={edit}
          value={value}
        />
      )}
    </div>
  )
}

type TargetFieldProps = {
  context: BiddingContext
  disabled: boolean
  invalid: boolean
  onEdit: (patch: Partial<Bidding>) => void
  value: Bidding
}

/** The labelled fields for the strategy's targets, or a target-only change's own targets. */
function TargetFields({ compact, ...props }: TargetFieldProps & { compact: boolean }) {
  const { strategy } = props.value
  const targets = strategy === TARGETS
  const share = strategy === "TARGET_IMPRESSION_SHARE"
  const fields = [
    strategy === "MAXIMIZE_CONVERSIONS" || (targets && props.value.target_cpa != null) ? (
      <TargetCpaField key="target_cpa" {...props} />
    ) : null,
    strategy === "MAXIMIZE_CONVERSION_VALUE" || (targets && props.value.target_roas != null) ? (
      <TargetRoasField key="target_roas" {...props} />
    ) : null,
    share ? <PagePositionField key="location" {...props} /> : null,
    share ? <ShareField key="share" {...props} /> : null,
    strategy === "MAXIMIZE_CLICKS" || share || (targets && props.value.max_cpc != null) ? (
      <MaxCpcField key="max_cpc" {...props} />
    ) : null,
  ].filter(Boolean)
  if (fields.length === 0) return null
  return (
    <div className={cn("grid gap-3", compact ? "sm:grid-cols-2" : "sm:grid-cols-3")}>{fields}</div>
  )
}

function optional(label: string, value: Bidding): string {
  return value.strategy === TARGETS ? label : `${label} (Optional)`
}

function TargetCpaField({ context, disabled, invalid, onEdit, value }: TargetFieldProps) {
  return (
    <MoneyField
      context={context}
      disabled={disabled}
      invalid={invalid}
      label={optional(TARGET_LABELS.target_cpa, value)}
      onCommit={(target_cpa) => {
        if (target_cpa !== null || value.strategy !== TARGETS) onEdit({ target_cpa })
      }}
      value={value.target_cpa ?? null}
    />
  )
}

function TargetRoasField({ disabled, invalid, onEdit, value }: TargetFieldProps) {
  return (
    <SuffixField
      disabled={disabled}
      invalid={invalid}
      label={optional(TARGET_LABELS.target_roas, value)}
      onCommit={(text) => {
        const percent = Number(text)
        if (!text && value.strategy !== TARGETS) onEdit({ target_roas: null })
        else if (text && Number.isFinite(percent) && percent > 0)
          onEdit({ target_roas: percent / 100 })
      }}
      suffix="%"
      value={value.target_roas != null ? roasPercent(value.target_roas) : ""}
    />
  )
}

function PagePositionField({ disabled, onEdit, value }: TargetFieldProps) {
  return (
    <FormField label="Where on the Page">
      {(id) => (
        <Select<string>
          disabled={disabled}
          onValueChange={(location) => {
            const known = PAGE_LOCATIONS.find((item) => item === location)
            if (known) onEdit({ location: known })
          }}
          value={value.location ?? null}
        >
          <SelectTrigger className="w-full" id={id}>
            <SelectValue placeholder="Choose" />
          </SelectTrigger>
          <SelectContent align="start">
            <SelectGroup>
              {PAGE_LOCATIONS.map((location) => (
                <SelectItem key={location} label={PAGE_POSITIONS[location]} value={location}>
                  {PAGE_POSITIONS[location]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      )}
    </FormField>
  )
}

function ShareField({ disabled, onEdit, value }: TargetFieldProps) {
  return (
    <SuffixField
      disabled={disabled}
      invalid={value.share_percent == null}
      label="Share of Searches"
      onCommit={(text) => {
        const percent = Number(text)
        if (text && Number.isInteger(percent) && percent >= 1 && percent <= 100)
          onEdit({ share_percent: percent })
      }}
      suffix="%"
      value={value.share_percent != null ? String(value.share_percent) : ""}
    />
  )
}

function MaxCpcField({ context, disabled, invalid, onEdit, value }: TargetFieldProps) {
  const clicks = value.strategy === "MAXIMIZE_CLICKS"
  return (
    <MoneyField
      context={context}
      disabled={disabled}
      invalid={(invalid && value.strategy === TARGETS) || (!clicks && !value.max_cpc)}
      label={clicks ? `${TARGET_LABELS.max_cpc} (Optional)` : TARGET_LABELS.max_cpc}
      onCommit={(max_cpc) => {
        // Google requires a ceiling for Target Impression Share.
        if (max_cpc !== null || clicks) onEdit({ max_cpc })
      }}
      value={value.max_cpc ?? null}
    />
  )
}

/** An amount in the account currency; empty commits null, and text that isn't money is ignored. */
function MoneyField({
  context,
  disabled,
  invalid,
  label,
  onCommit,
  value,
}: {
  context: BiddingContext
  disabled: boolean
  invalid: boolean
  label: string
  onCommit: (value: string | null) => void
  value: string | null
}) {
  const symbol = context.currency ? currencySymbol(context.currency) : null
  return (
    <FormField label={label}>
      {(id) => (
        <div className="relative flex items-center">
          {symbol ? (
            <span
              aria-hidden="true"
              className="text-muted-foreground pointer-events-none absolute left-2.5 text-sm"
            >
              {symbol}
            </span>
          ) : null}
          <CommittedInput
            ariaLabel={label}
            className={cn(
              "h-8 text-sm tabular-nums",
              symbol && "pl-7",
              invalid && "border-destructive"
            )}
            disabled={disabled}
            id={id}
            onCommit={(next) => {
              const trimmed = next.trim()
              if (!trimmed) onCommit(null)
              else if (parseGoogleAdsMoney(trimmed)) onCommit(canonicalMoney(trimmed))
            }}
            placeholder="None"
            value={value === null ? "" : moneyInput(value)}
          />
        </div>
      )}
    </FormField>
  )
}

function SuffixField({
  disabled,
  invalid,
  label,
  onCommit,
  suffix,
  value,
}: {
  disabled: boolean
  invalid: boolean
  label: string
  onCommit: (value: string) => void
  suffix: string
  value: string
}) {
  return (
    <FormField label={label}>
      {(id) => (
        <div className="relative flex items-center">
          <CommittedInput
            ariaLabel={label}
            className={cn("h-8 pr-7 text-sm tabular-nums", invalid && "border-destructive")}
            disabled={disabled}
            id={id}
            onCommit={(next) => {
              onCommit(next.trim())
            }}
            placeholder="None"
            value={value}
          />
          <span
            aria-hidden="true"
            className="text-muted-foreground pointer-events-none absolute right-2.5 text-sm"
          >
            {suffix}
          </span>
        </div>
      )}
    </FormField>
  )
}
