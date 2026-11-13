// apps/web/src/integrations/google_ads/components/targeting-audiences.tsx

import { PlusIcon, XIcon } from "lucide-react"
import { useState, type ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ChoiceCards } from "@/integrations/ads/components/controls"
import { EntitySearch } from "@/integrations/ads/components/entity-search"
import type { EntityChoice } from "@/features/tools/types"
import { BidAdjustment } from "@/integrations/google_ads/components/bid-adjustment"
import {
  AUDIENCE_MODE_OPTIONS,
  audienceCategory,
  audienceLines,
  shownAudienceMode,
  unchangedAudiences,
  type AudienceLine,
  type DemographicLine,
} from "@/integrations/google_ads/lib/targeting-audiences"
import {
  deviceText,
  EXCLUDED,
  type AudienceMode,
  type DemographicTarget,
  type UpdateTargetingArgs,
} from "@/integrations/google_ads/lib/update-targeting"

const TOOL = "google_ads_update_targeting"
// How many unchanged audiences the card lists before trimming.
const MAX_UNCHANGED = 5

function Row({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-12 min-w-0 flex-wrap items-center gap-2.5 py-1 pr-1.5 pl-3">
      {children}
    </div>
  )
}

function Name({ detail, name }: { detail?: string | null; name: string }) {
  return (
    <div className="grid min-w-32 flex-1 text-sm">
      <span className="font-medium wrap-anywhere">{name}</span>
      {detail ? (
        <span className="text-muted-foreground text-xs wrap-anywhere">{detail}</span>
      ) : null}
    </div>
  )
}

function Count({ count, noun, show }: { count: number; noun: string; show: boolean }) {
  return show ? (
    <span className="text-muted-foreground text-sm whitespace-nowrap tabular-nums">
      {String(count)} {count === 1 ? noun : `${noun}s`}
    </span>
  ) : null
}

function CancelButton({
  disabled,
  label,
  onClick,
}: {
  disabled: boolean
  label: string
  onClick: () => void
}) {
  return (
    <Button
      aria-label={label}
      className="size-11 shrink-0"
      disabled={disabled}
      onClick={onClick}
      size="icon"
      title="Cancel This Change"
      type="button"
      variant="ghost"
    >
      <XIcon aria-hidden="true" />
    </Button>
  )
}

/** The audiences added and removed, the ones left alone, and how the entry uses them. */
export function AudienceRows({
  args,
  disabled,
  noun,
  onAdd,
  onBid,
  onCancel,
  onMode,
}: {
  args: UpdateTargetingArgs
  disabled: boolean
  // What each count counts, such as "ad group".
  noun: string
  onAdd: (choice: EntityChoice) => void
  onBid: (id: string, bid: number | null) => void
  onCancel: (field: AudienceLine["field"], id: string) => void
  onMode: (mode: AudienceMode | null) => void
}) {
  const [adding, setAdding] = useState(false)
  const lines = audienceLines(args)
  const unchanged = unchangedAudiences(args)
  const many = args.changes.length > 1
  const requested = args.changes.some((change) => change.audienceMode !== null)
  const mode = shownAudienceMode(args)
  // The mode only applies to audiences the entries keep, so removals alone don't ask for it.
  const keepsAudiences =
    unchanged.length > 0 || lines.some((line) => line.field === "add_audiences")
  return (
    <div className="divide-y">
      {lines.map((line) => {
        const adds = line.field === "add_audiences"
        const label = adds ? "Adding" : "Removing"
        return (
          <Row key={`${line.field}:${line.id}`}>
            <Name detail={audienceCategory(line.kind)} name={line.name} />
            <Count count={line.count} noun={noun} show={many} />
            <Badge variant={adds ? "success" : "destructive"}>{label}</Badge>
            {adds ? (
              <BidAdjustment
                disabled={disabled}
                label={`Bid adjustment for ${line.name}`}
                onChange={(bid) => {
                  onBid(line.id, bid)
                }}
                value={line.bidAdjustment}
              />
            ) : null}
            <CancelButton
              disabled={disabled}
              label={`Cancel ${label.toLowerCase()} ${line.name}`}
              onClick={() => {
                onCancel(line.field, line.id)
              }}
            />
          </Row>
        )
      })}
      {unchanged.slice(0, MAX_UNCHANGED).map((audience) => (
        <Row key={audience.id}>
          <Name name={audience.name} />
          <Count count={audience.count} noun={noun} show={many} />
          <Badge className="mr-1.5" variant="secondary">
            No Change
          </Badge>
        </Row>
      ))}
      {unchanged.length > MAX_UNCHANGED ? (
        <p className="text-muted-foreground px-3 py-2 text-sm">
          And {String(unchanged.length - MAX_UNCHANGED)} more with no change.
        </p>
      ) : null}
      {adding ? (
        <div className="bg-muted/40 grid gap-3 p-3">
          <EntitySearch
            disabled={disabled}
            entityKind="google_ads_audience"
            fieldKey="changes"
            isTaken={(choice) =>
              lines.some(
                (line) =>
                  line.field === "add_audiences" &&
                  line.id === `${String(choice.value["kind"])}:${String(choice.value["key"])}`
              )
            }
            label="Search for an audience"
            onChoose={onAdd}
            placeholder="Search your lists, interests, and custom audiences"
            searchRequired
            toolName={TOOL}
          />
          <Button
            className="w-fit"
            onClick={() => {
              setAdding(false)
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            Done Adding
          </Button>
        </div>
      ) : (
        <div className="p-1.5">
          <Button
            disabled={disabled}
            onClick={() => {
              setAdding(true)
            }}
            type="button"
            variant="ghost"
          >
            <PlusIcon aria-hidden="true" />
            Add an Audience
          </Button>
        </div>
      )}
      {keepsAudiences ? (
        <div className="grid gap-2 p-3">
          <ChoiceCards
            ariaLabel="How to use these audiences"
            columns={2}
            disabled={disabled}
            onChange={(value) => {
              onMode(value as AudienceMode)
            }}
            options={AUDIENCE_MODE_OPTIONS}
            value={mode ?? ""}
          />
          {requested ? (
            <Button
              className="w-fit"
              disabled={disabled}
              onClick={() => {
                onMode(null)
              }}
              size="sm"
              type="button"
              variant="ghost"
            >
              Keep How Audiences Are Used Now
            </Button>
          ) : mode === null ? (
            <p className="text-muted-foreground text-sm">
              Google&apos;s default applies until you choose.
            </p>
          ) : null}
        </div>
      ) : requested && mode ? (
        <Row>
          <Name
            detail="No audiences are left after this change, so this has no effect."
            name={`Audience Use: ${mode === "OBSERVATION" ? "Observation" : "Targeting"}`}
          />
          <CancelButton
            disabled={disabled}
            label="Cancel the change to audience use"
            onClick={() => {
              onMode(null)
            }}
          />
        </Row>
      ) : null}
    </div>
  )
}

function nowText(line: DemographicLine): string {
  if (line.now === null) return "Now: differs"
  const text = deviceText({ bidAdjustment: line.now, excluded: false })
  return `Now: ${text.charAt(0).toUpperCase()}${text.slice(1)}`
}

/** One row per value of a dimension, with its adjustment now and the change asked for. */
export function DemographicAdjustments({
  disabled,
  exclusionsOnly,
  lines,
  onChange,
}: {
  disabled: boolean
  // Performance Max can exclude a group but can't adjust bids for one.
  exclusionsOnly: boolean
  lines: readonly DemographicLine[]
  // Null leaves the value as it is.
  onChange: (
    value: string,
    next: Pick<DemographicTarget, "bidAdjustment" | "excluded"> | null
  ) => void
}) {
  return (
    <div className="divide-y">
      {lines.map((line) => {
        // One edit here would replace what each entry asks for with a single value.
        const varies = line.requested === "varies"
        const asked = line.requested === "varies" ? null : line.requested
        const excluded = asked ? asked.excluded : line.now === EXCLUDED
        const bid = asked ? asked.bidAdjustment : line.now
        // An adjustment the request asks for still shows, so it can be cleared.
        const adjustable = !exclusionsOnly || (!excluded && asked !== null && bid !== 0)
        return (
          <Row key={line.value}>
            <Name
              detail={varies ? "Changes differ. Choose one above to change it." : nowText(line)}
              name={line.name}
            />
            {line.requested === null ? (
              <Badge className="mr-1.5" variant="secondary">
                No Change
              </Badge>
            ) : (
              <Badge variant={excluded ? "destructive" : "success"}>
                {excluded ? "Excluding" : "Changing"}
              </Badge>
            )}
            {adjustable ? (
              <BidAdjustment
                disabled={disabled || excluded || varies}
                label={`Bid adjustment for ${line.name}`}
                onChange={(bidAdjustment) => {
                  onChange(line.value, { bidAdjustment: bidAdjustment ?? 0, excluded: false })
                }}
                value={excluded || bid === null || bid === 0 ? null : bid}
              />
            ) : null}
            <Button
              aria-pressed={excluded}
              disabled={disabled || varies}
              onClick={() => {
                onChange(line.value, { bidAdjustment: 0, excluded: !excluded })
              }}
              size="sm"
              title={excluded ? "Show ads to this group again" : "Stop ads showing to this group"}
              type="button"
              variant={excluded ? "secondary" : "outline"}
            >
              {excluded ? "Excluded" : "Exclude"}
            </Button>
            {line.requested === null ? (
              <span aria-hidden="true" className="size-11 shrink-0" />
            ) : (
              <CancelButton
                disabled={disabled}
                label={`Cancel the change to ${line.name}`}
                onClick={() => {
                  onChange(line.value, null)
                }}
              />
            )}
          </Row>
        )
      })}
    </div>
  )
}
