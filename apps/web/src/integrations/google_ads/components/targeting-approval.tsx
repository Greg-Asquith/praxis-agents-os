// apps/web/src/integrations/google_ads/components/targeting-approval.tsx

import { InfoIcon, PlusIcon, XIcon } from "lucide-react"
import { useMemo, useState, type ReactNode } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableTab,
} from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { SegmentedChoice } from "@/integrations/ads/components/controls"
import { EntitySearch } from "@/integrations/ads/components/entity-search"
import { SettingRow, SettingRows } from "@/integrations/ads/components/setting-rows"
import type { EntityChoice } from "@/features/tools/types"
import { BidAdjustment } from "@/integrations/google_ads/components/bid-adjustment"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { LocationPaste } from "@/integrations/google_ads/components/location-paste"
import { LOCATION_SETTING_LABELS } from "@/integrations/google_ads/lib/update-targeting-result"
import {
  acceptsLanguageAdds,
  addTarget,
  campaignRows,
  campaignsByDifference,
  campaignsOn,
  clearedChange,
  editRadius,
  keepRadius,
  languagesText,
  needsCheck,
  parseCancelled,
  radiusIdentity,
  radiusLines,
  radiusRemovals,
  radiusText,
  removeTarget,
  serializeChanges,
  setBidAdjustment,
  setLocationSetting,
  shownLocationSetting,
  targetingCounts,
  targetLines,
  unchangedLanguages,
  unchangedPlaces,
  unchangedRadius,
  whatChanges,
  type CampaignRow,
  type LocationSetting,
  type RadiusTarget,
  type RadiusUnits,
  type Target,
  type TargetField,
  type TargetingChange,
  type TargetLine,
  type UpdateTargetingArgs,
} from "@/integrations/google_ads/lib/update-targeting"

const TOOL = "google_ads_update_targeting"
// More places of one type than this collapse to one row with a Review control.
const GROUP_FROM = 8
// How many unchanged places, blocked campaigns, and campaigns the card lists before trimming.
const MAX_UNCHANGED = 5
const MAX_BLOCKED = 3
const MAX_CAMPAIGNS = 3
// Below this many campaigns the table's search and tabs only add noise.
const TOOLS_FROM = 10

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Campaign", width: 220 },
  { key: "changes", kind: "text", label: "What Changes", width: 160 },
  { key: "languages", kind: "text", label: "Languages", width: 150 },
  { key: "cancel", kind: "text", label: "Cancel", width: 180 },
]

const TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  {
    id: "already",
    label: "Already Set",
    hideWhenEmpty: true,
    match: (row) => row["state"] === "already",
  },
  {
    id: "attention",
    label: "Needs Attention",
    hideWhenEmpty: true,
    match: (row) => row["state"] === "attention",
  },
]

const SETTING_OPTIONS: readonly { label: string; value: LocationSetting }[] = [
  { label: "In, or Interested In", value: "PRESENCE_OR_INTEREST" },
  { label: "In or Regularly In", value: "PRESENCE" },
]

const UNIT_OPTIONS: readonly { label: string; value: RadiusUnits }[] = [
  { label: "Miles", value: "MILES" },
  { label: "Kilometres", value: "KILOMETERS" },
]

const LOCATION_FIELDS = ["add_locations", "exclude_locations", "remove_locations"] as const

const LOCATION_BADGES: Partial<
  Record<TargetField, { label: string; variant: "success" | "destructive" }>
> = {
  add_locations: { label: "Adding", variant: "success" },
  exclude_locations: { label: "Excluding", variant: "destructive" },
  remove_locations: { label: "Removing", variant: "destructive" },
}

function targetOf(choice: EntityChoice): Target | null {
  const { key, name, target_type: targetType } = choice.value
  if (typeof key !== "string") return null
  return {
    bidAdjustment: null,
    key,
    name: typeof name === "string" ? name : choice.label,
    targetType: typeof targetType === "string" ? targetType : null,
  }
}

function typeNoun(targetType: string | null): string {
  return targetType === "Postal Code" ? "Postcode" : (targetType ?? "Location")
}

function campaignCount(count: number, show: boolean): ReactNode {
  return show ? (
    <span className="text-muted-foreground text-sm whitespace-nowrap tabular-nums">
      {String(count)} {count === 1 ? "campaign" : "campaigns"}
    </span>
  ) : null
}

export function TargetingApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: UpdateTargetingArgs
  // The request Google last answered for.
  checked: UpdateTargetingArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const [adding, setAdding] = useState(false)
  const cancelled = useMemo(() => parseCancelled(controls.retained), [controls.retained])
  const rows = useMemo(() => campaignRows(args, checked, cancelled), [args, checked, cancelled])
  const counts = targetingCounts(rows)
  const lines = useMemo(() => targetLines(args), [args])
  const many = rows.length > 1
  const blocked = rows.filter((row) => row.problems.length > 0 && !row.cancelled)

  // A campaign left with nothing leaves the request, and stays beside it so Undo can restore it.
  const save = (next: readonly TargetingChange[]) => {
    const kept = new Set(next.map((change) => change.key))
    const dropped = args.changes.filter((change) => !kept.has(change.key))
    const restored = cancelled.filter((change) => !kept.has(change.key))
    if (dropped.length > 0 || restored.length !== cancelled.length)
      controls.onRetain?.(serializeChanges([...restored, ...dropped]))
    onFieldEdit("changes", serializeChanges(next))
  }
  const cancelCampaign = (key: string) => {
    save(args.changes.filter((change) => change.key !== key))
  }
  const undo = (key: string) => {
    const change = cancelled.find((item) => item.key === key)
    if (change) save([...args.changes, change])
  }
  // With every campaign cancelled, what the operator adds next starts them again from nothing.
  const addable = () => (args.changes.length > 0 ? args.changes : cancelled.map(clearedChange))
  const addTargets = (field: TargetField, choices: readonly EntityChoice[]) => {
    let changes: readonly TargetingChange[] = addable()
    for (const choice of choices) {
      const target = targetOf(choice)
      if (target) {
        changes = addTarget(changes, field, target, (change) =>
          field === "add_languages" ? acceptsLanguageAdds(args, change) : true
        )
      }
    }
    save(changes)
  }
  const removeMany = (field: TargetField, keys: readonly string[]) => {
    let changes: readonly TargetingChange[] = args.changes
    for (const key of keys) changes = removeTarget(changes, field, key)
    save(changes)
  }

  return (
    <div className="grid min-w-0 gap-3">
      <StatusNote args={args} />
      {blocked.slice(0, MAX_BLOCKED).map((row) => (
        <BlockedCampaign
          key={row.key}
          disabled={disabled}
          onCancel={() => {
            cancelCampaign(row.key)
          }}
          row={row}
        />
      ))}
      {blocked.length > MAX_BLOCKED ? (
        <p className="text-destructive text-sm">
          {String(blocked.length - MAX_BLOCKED)} more need attention. They&apos;re first in the
          campaign table.
        </p>
      ) : null}
      <section aria-label="Where ads can show" className="overflow-hidden rounded-lg border">
        <h4 className="bg-muted/40 border-b px-3 py-2 text-sm font-semibold">Where Ads Can Show</h4>
        <div className="divide-y">
          <LocationRows
            args={args}
            disabled={disabled}
            lines={lines}
            many={many}
            onBid={(key, bid) => {
              save(setBidAdjustment(args.changes, new Set([key]), bid))
            }}
            onCancel={removeMany}
            onKeepRadius={(id) => {
              save(keepRadius(args.changes, id))
            }}
            onRadius={(identity, next) => {
              save(editRadius(args.changes, identity, next))
            }}
          />
          {adding ? (
            <AddPanel
              disabled={disabled}
              lines={lines}
              onAdd={addTargets}
              onDone={() => {
                setAdding(false)
              }}
              onRadius={(target) => {
                save(editRadius(addable(), null, target))
              }}
            />
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
                Add or Exclude a Location
              </Button>
            </div>
          )}
        </div>
      </section>
      <LanguageSection
        args={args}
        disabled={disabled}
        lines={lines}
        many={many}
        onAdd={(choice) => {
          addTargets("add_languages", [choice])
        }}
        onCancel={removeMany}
      />
      {many ? (
        <CampaignTable disabled={disabled} onCancel={cancelCampaign} onUndo={undo} rows={rows} />
      ) : counts.total === 0 && rows[0] ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2">
          <p className="text-muted-foreground text-sm">Nothing is left to change.</p>
          <Button
            disabled={disabled}
            onClick={() => {
              undo(rows[0]?.key ?? "")
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            Undo
          </Button>
        </div>
      ) : null}
      <SettingRows ariaLabel="More settings" defaultOpen={null}>
        <SettingRow rowKey="location-setting" summary={settingSummary(args)} title="Who Counts">
          <SegmentedChoice
            ariaLabel="Who counts as being in these places"
            disabled={disabled}
            onChange={(value: LocationSetting) => {
              save(setLocationSetting(args.changes, value))
            }}
            options={SETTING_OPTIONS}
            value={shownLocationSetting(args)}
          />
          {args.changes.some((change) => change.setting !== null) ? (
            <Button
              className="w-fit"
              disabled={disabled}
              onClick={() => {
                save(setLocationSetting(args.changes, null))
              }}
              size="sm"
              type="button"
              variant="ghost"
            >
              Cancel This Change
            </Button>
          ) : null}
        </SettingRow>
      </SettingRows>
      {needsCheck(args, checked) && args.changes.length > 0 ? (
        <CheckChanges
          canCheck
          disabled={disabled}
          label={
            [...checked.checks.values()].some((check) => check.unavailable)
              ? "Check Again"
              : "Check Changes"
          }
          note="You changed this request, so Google needs to check it again."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
    </div>
  )
}

function settingSummary(args: UpdateTargetingArgs): string {
  const shown = `${LOCATION_SETTING_LABELS[shownLocationSetting(args)] ?? "People in"} these places`
  return args.changes.some((change) => change.setting !== null) ? `Changing to: ${shown}` : shown
}

/** States what approving does now: a paused campaign shows no ads until someone turns it on. */
function StatusNote({ args }: { args: UpdateTargetingArgs }) {
  const total = args.changes.length
  if (total === 0) return null
  const on = campaignsOn(args)
  if (on === 0)
    return (
      <p className="bg-muted text-foreground/80 flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm">
        <InfoIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        {total === 1
          ? "This campaign is paused, so it won't show ads in these places until it's turned on."
          : "These campaigns are paused, so they won't show ads in these places until they're turned on."}
      </p>
    )
  const detail =
    on === null
      ? `${String(total)} ${total === 1 ? "campaign" : "campaigns"}`
      : total === 1
        ? "This campaign is on."
        : `${String(on)} of ${String(total)} campaigns are on.`
  return <ChangeBanner detail={detail} />
}

function BlockedCampaign({
  disabled,
  onCancel,
  row,
}: {
  disabled: boolean
  onCancel: () => void
  row: CampaignRow
}) {
  return (
    <div
      className="border-destructive/30 bg-destructive/5 flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2"
      role="alert"
    >
      <div className="grid min-w-0 flex-1 gap-0.5 text-sm">
        <span className="font-medium wrap-anywhere">{row.name} Needs Attention</span>
        {row.problems.map((problem) => (
          <span key={problem} className="text-destructive wrap-anywhere">
            {problem}
          </span>
        ))}
      </div>
      <Button disabled={disabled} onClick={onCancel} size="sm" type="button" variant="outline">
        Cancel This Change
      </Button>
    </div>
  )
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
      type="button"
      variant="ghost"
    >
      <XIcon aria-hidden="true" />
    </Button>
  )
}

function Row({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-12 min-w-0 flex-wrap items-center gap-2.5 py-1 pr-1.5 pl-3">
      {children}
    </div>
  )
}

function Place({ detail, name }: { detail?: string | null | undefined; name: string }) {
  return (
    <div className="grid min-w-32 flex-1 text-sm">
      <span className="font-medium wrap-anywhere">{name}</span>
      {detail ? (
        <span className="text-muted-foreground text-xs wrap-anywhere">{detail}</span>
      ) : null}
    </div>
  )
}

function LocationRows({
  args,
  disabled,
  lines,
  many,
  onBid,
  onCancel,
  onKeepRadius,
  onRadius,
}: {
  args: UpdateTargetingArgs
  disabled: boolean
  lines: readonly TargetLine[]
  many: boolean
  onBid: (key: string, bid: number | null) => void
  onCancel: (field: TargetField, keys: readonly string[]) => void
  onKeepRadius: (id: string) => void
  onRadius: (identity: string, next: RadiusTarget | null) => void
}) {
  const radii = radiusLines(args)
  const removals = radiusRemovals(args)
  return (
    <>
      {LOCATION_FIELDS.map((field) => (
        <TargetRows
          key={field}
          disabled={disabled}
          field={field}
          lines={lines.filter((line) => line.field === field)}
          many={many}
          onBid={onBid}
          onCancel={onCancel}
        />
      ))}
      {radii.map((target) => (
        <RadiusRow
          key={radiusIdentity(target)}
          disabled={disabled}
          many={many}
          onChange={(next) => {
            onRadius(radiusIdentity(target), next)
          }}
          target={target}
        />
      ))}
      {removals.map((target) => (
        <Row key={target.id}>
          <Place name={target.text} />
          {campaignCount(target.count, many)}
          <Badge variant="destructive">Removing</Badge>
          <CancelButton
            disabled={disabled}
            label={`Cancel removing ${target.text}`}
            onClick={() => {
              onKeepRadius(target.id)
            }}
          />
        </Row>
      ))}
      <UnchangedRows
        args={args}
        hasAdds={lines.some((l) => l.field === "add_locations")}
        many={many}
      />
    </>
  )
}

function TargetRows({
  disabled,
  field,
  lines,
  many,
  onBid,
  onCancel,
}: {
  disabled: boolean
  field: (typeof LOCATION_FIELDS)[number]
  lines: readonly TargetLine[]
  many: boolean
  onBid: (key: string, bid: number | null) => void
  onCancel: (field: TargetField, keys: readonly string[]) => void
}) {
  const [reviewing, setReviewing] = useState<string | null>(null)
  const groups = new Map<string, TargetLine[]>()
  for (const line of lines) {
    const noun = typeNoun(line.targetType)
    groups.set(noun, [...(groups.get(noun) ?? []), line])
  }
  const badge = LOCATION_BADGES[field]
  const single = (line: TargetLine) => (
    <Row key={line.key}>
      <Place detail={line.targetType} name={line.name} />
      {campaignCount(line.count, many)}
      {badge ? <Badge variant={badge.variant}>{badge.label}</Badge> : null}
      {field === "add_locations" ? (
        <BidAdjustment
          disabled={disabled}
          label={`Bid adjustment for ${line.name}`}
          onChange={(bid) => {
            onBid(line.key, bid)
          }}
          value={line.bidAdjustment}
        />
      ) : null}
      <CancelButton
        disabled={disabled}
        label={`Cancel ${badge?.label.toLowerCase() ?? "changing"} ${line.name}`}
        onClick={() => {
          onCancel(field, [line.key])
        }}
      />
    </Row>
  )
  return (
    <>
      {[...groups].map(([noun, items]) => {
        if (items.length < GROUP_FROM) return items.map(single)
        const open = reviewing === noun
        const name = `${String(items.length)} ${noun}s`
        const shown = items.slice(0, 3).map((item) => item.name)
        return (
          <div key={noun} className="divide-y">
            <Row>
              <Place
                detail={`${shown.join(", ")}, and ${String(items.length - shown.length)} more`}
                name={name}
              />
              {campaignCount(Math.max(...items.map((item) => item.count)), many)}
              {badge ? <Badge variant={badge.variant}>{badge.label}</Badge> : null}
              <Button
                onClick={() => {
                  setReviewing(open ? null : noun)
                }}
                size="sm"
                type="button"
                variant="ghost"
              >
                {open ? "Hide" : "Review"}
              </Button>
              <CancelButton
                disabled={disabled}
                label={`Cancel ${badge?.label.toLowerCase() ?? "changing"} ${name}`}
                onClick={() => {
                  onCancel(
                    field,
                    items.map((item) => item.key)
                  )
                }}
              />
            </Row>
            {open ? (
              <div className="max-h-72 divide-y overflow-y-auto">{items.map(single)}</div>
            ) : null}
          </div>
        )
      })}
    </>
  )
}

function UnchangedRows({
  args,
  hasAdds,
  many,
}: {
  args: UpdateTargetingArgs
  hasAdds: boolean
  many: boolean
}) {
  const places = unchangedPlaces(args)
  const radii = unchangedRadius(args)
  const hidden = Math.max(0, places.length - MAX_UNCHANGED)
  const included = places.some((place) => !place.excluded) || radii.length > 0
  return (
    <>
      {places.slice(0, MAX_UNCHANGED).map((place) => (
        <Row key={`${String(place.excluded)}:${place.key}`}>
          <Place name={place.name} />
          {campaignCount(place.count, many)}
          <Badge className="mr-1.5" variant="secondary">
            {place.excluded ? "Already Excluded" : "No Change"}
          </Badge>
        </Row>
      ))}
      {radii.map((radius) => (
        <Row key={radius.text}>
          <Place name={radius.text} />
          {campaignCount(radius.count, many)}
          <Badge className="mr-1.5" variant="secondary">
            No Change
          </Badge>
        </Row>
      ))}
      {hidden > 0 ? (
        <p className="text-muted-foreground px-3 py-2 text-sm">
          And {String(hidden)} more with no change.
        </p>
      ) : null}
      {!included && !hasAdds && args.changes.length > 0 ? (
        <Row>
          <Place name="All Locations" />
          <Badge className="mr-1.5" variant="secondary">
            No Change
          </Badge>
        </Row>
      ) : null}
    </>
  )
}

function RadiusRow({
  disabled,
  many,
  onChange,
  target,
}: {
  disabled: boolean
  many: boolean
  onChange: (next: RadiusTarget | null) => void
  target: RadiusTarget & { count: number }
}) {
  return (
    <Row>
      <Place detail={radiusText(target)} name={target.label ?? "Distance Around a Place"} />
      {campaignCount(target.count, many)}
      <Badge variant="success">Adding</Badge>
      <Input
        aria-label="Distance"
        className="w-20 tabular-nums"
        defaultValue={String(target.radius)}
        disabled={disabled}
        inputMode="decimal"
        onBlur={(event) => {
          const radius = Number(event.currentTarget.value)
          if (radius > 0 && radius !== target.radius) onChange({ ...target, radius })
        }}
      />
      <SegmentedChoice
        ariaLabel="Distance units"
        compact
        disabled={disabled}
        onChange={(units: RadiusUnits) => {
          onChange({ ...target, units })
        }}
        options={UNIT_OPTIONS}
        value={target.units}
      />
      <BidAdjustment
        disabled={disabled}
        label="Bid adjustment for this distance"
        onChange={(bidAdjustment) => {
          onChange({ ...target, bidAdjustment })
        }}
        value={target.bidAdjustment}
      />
      <CancelButton
        disabled={disabled}
        label="Cancel adding this distance"
        onClick={() => {
          onChange(null)
        }}
      />
    </Row>
  )
}

function AddPanel({
  disabled,
  lines,
  onAdd,
  onDone,
  onRadius,
}: {
  disabled: boolean
  lines: readonly TargetLine[]
  onAdd: (field: TargetField, choices: readonly EntityChoice[]) => void
  onDone: () => void
  onRadius: (target: RadiusTarget) => void
}) {
  const [tab, setTab] = useState("search")
  const [field, setField] = useState<"add_locations" | "exclude_locations">("add_locations")
  return (
    <div className="bg-muted/40 grid min-w-0 gap-3 p-3">
      <Tabs
        onValueChange={(value) => {
          setTab(String(value))
        }}
        value={tab}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <TabsList>
            <TabsTrigger value="search">Search</TabsTrigger>
            <TabsTrigger value="paste">Paste a List</TabsTrigger>
            <TabsTrigger value="radius">Distance Around a Place</TabsTrigger>
          </TabsList>
          {tab === "radius" ? null : (
            <SegmentedChoice
              ariaLabel="What to do with this location"
              disabled={disabled}
              onChange={setField}
              options={[
                { label: "Show Ads", value: "add_locations" },
                { label: "Don't Show Ads", value: "exclude_locations" },
              ]}
              value={field}
            />
          )}
        </div>
        <TabsContent className="pt-3" value="search">
          <EntitySearch
            disabled={disabled}
            entityKind="google_ads_location"
            fieldKey="changes"
            isTaken={(choice) =>
              lines.some((line) => line.field === field && line.key === choice.value["key"])
            }
            label="Search for a location"
            onChoose={(choice) => {
              onAdd(field, [choice])
            }}
            placeholder="Search cities, regions, or postcodes"
            searchRequired
            toolName={TOOL}
          />
        </TabsContent>
        <TabsContent className="pt-3" value="paste">
          <LocationPaste
            disabled={disabled}
            onFound={(choices) => {
              onAdd(field, choices)
            }}
            toolName={TOOL}
          />
        </TabsContent>
        <TabsContent className="pt-3" value="radius">
          <RadiusForm disabled={disabled} onAdd={onRadius} />
        </TabsContent>
      </Tabs>
      <Button className="w-fit" onClick={onDone} size="sm" type="button" variant="outline">
        Done Adding
      </Button>
    </div>
  )
}

function LanguageSection({
  args,
  disabled,
  lines,
  many,
  onAdd,
  onCancel,
}: {
  args: UpdateTargetingArgs
  disabled: boolean
  lines: readonly TargetLine[]
  many: boolean
  onAdd: (choice: EntityChoice) => void
  onCancel: (field: TargetField, keys: readonly string[]) => void
}) {
  const [adding, setAdding] = useState(false)
  const anyAccepts = args.changes.some((change) => acceptsLanguageAdds(args, change))
  const someRefuse = args.changes.some((change) => !acceptsLanguageAdds(args, change))
  const changing = lines.filter(
    (line) => line.field === "add_languages" || line.field === "remove_languages"
  )
  // Search campaigns ignore languages, so the section only appears when one is changing.
  if (!anyAccepts && changing.length === 0) return null
  return (
    <section aria-label="Languages" className="overflow-hidden rounded-lg border">
      <h4 className="bg-muted/40 border-b px-3 py-2 text-sm font-semibold">Languages</h4>
      <div className="divide-y">
        {changing.map((line) => {
          const adds = line.field === "add_languages"
          const label = adds ? "Adding" : "Removing"
          return (
            <Row key={`${line.field}:${line.key}`}>
              <Place name={line.name} />
              {campaignCount(line.count, many)}
              <Badge variant={adds ? "success" : "destructive"}>{label}</Badge>
              <CancelButton
                disabled={disabled}
                label={`Cancel ${label.toLowerCase()} ${line.name}`}
                onClick={() => {
                  onCancel(line.field, [line.key])
                }}
              />
            </Row>
          )
        })}
        {anyAccepts
          ? unchangedLanguages(args).map((language) => (
              <Row key={language.key}>
                <Place name={language.name} />
                {campaignCount(language.count, many)}
                <Badge className="mr-1.5" variant="secondary">
                  No Change
                </Badge>
              </Row>
            ))
          : null}
        {anyAccepts ? (
          adding ? (
            <div className="bg-muted/40 grid gap-3 p-3">
              <EntitySearch
                disabled={disabled}
                entityKind="google_ads_language"
                fieldKey="changes"
                isTaken={(choice) =>
                  lines.some(
                    (line) => line.field === "add_languages" && line.key === choice.value["key"]
                  )
                }
                label="Search for a language"
                onChoose={onAdd}
                placeholder="Search languages"
                searchRequired
                toolName={TOOL}
              />
              {someRefuse ? (
                <p className="text-muted-foreground text-sm">
                  Search campaigns are left out, because Google matches each ad&apos;s language.
                </p>
              ) : null}
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
                Add a Language
              </Button>
            </div>
          )
        ) : null}
      </div>
    </section>
  )
}

function CampaignTable({
  disabled,
  onCancel,
  onUndo,
  rows,
}: {
  disabled: boolean
  onCancel: (key: string) => void
  onUndo: (key: string) => void
  rows: readonly CampaignRow[]
}) {
  const [all, setAll] = useState(false)
  const ordered = useMemo(() => campaignsByDifference(rows), [rows])
  const trimmed = !all && ordered.length > MAX_CAMPAIGNS
  const byKey = useMemo(() => new Map(rows.map((row) => [row.key, row])), [rows])
  const tableRows = useMemo<DataRow[]>(
    () =>
      (trimmed ? ordered.slice(0, MAX_CAMPAIGNS) : ordered).map((row) => ({
        cancel: "",
        changes: row.cancelled ? "Left as it is" : whatChanges(row.change),
        key: row.key,
        languages: languagesText(row.change, row.check),
        name: row.name,
        state: row.problems.length > 0 ? "attention" : row.alreadySet ? "already" : "live",
      })),
    [ordered, trimmed]
  )
  const tools = all && ordered.length >= TOOLS_FROM
  return (
    <section aria-label="Campaigns" className="grid min-w-0 gap-1.5">
      <p className="text-sm font-semibold">
        Campaigns
        {trimmed ? (
          <span className="text-muted-foreground font-normal">
            {" "}
            Showing the {String(MAX_CAMPAIGNS)} most different of {String(ordered.length)}
          </span>
        ) : null}
      </p>
      <DataTable
        columns={COLUMNS}
        exportFilename="google-ads-targeting-changes.csv"
        pageSize={25}
        renderCell={(column, row) => {
          const campaign = byKey.get(String(row["key"]))
          if (!campaign) return null
          if (column.key === "name") return <CampaignCell row={campaign} />
          if (column.key === "changes" || column.key === "languages")
            return (
              <span className="text-sm wrap-anywhere whitespace-normal">
                {cellText(row[column.key])}
              </span>
            )
          if (column.key === "cancel")
            return (
              <Button
                disabled={disabled}
                onClick={() => {
                  if (campaign.cancelled) onUndo(campaign.key)
                  else onCancel(campaign.key)
                }}
                size="sm"
                type="button"
                variant="ghost"
              >
                {campaign.cancelled ? "Undo" : "Cancel This Change"}
              </Button>
            )
          return null
        }}
        rowClassName={(row) =>
          byKey.get(String(row["key"]))?.cancelled ? "opacity-60" : undefined
        }
        rowDetails={false}
        rowNoun={["campaign", "campaigns"]}
        rows={tableRows}
        {...(tools ? { searchable: true, tabs: TABS } : {})}
      />
      {trimmed ? (
        <Button
          className="w-fit"
          onClick={() => {
            setAll(true)
          }}
          size="sm"
          type="button"
          variant="ghost"
        >
          Show All {String(ordered.length)} Campaigns
        </Button>
      ) : null}
    </section>
  )
}

function cellText(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function CampaignCell({ row }: { row: CampaignRow }) {
  return (
    <div className="grid min-w-0 gap-0.5 text-sm whitespace-normal">
      <span className="font-medium wrap-anywhere">{row.name}</span>
      {!row.cancelled && row.problems.length > 0 ? (
        <span className="text-destructive text-xs">Needs Attention</span>
      ) : null}
    </div>
  )
}

function RadiusForm({
  disabled,
  onAdd,
}: {
  disabled: boolean
  onAdd: (target: RadiusTarget) => void
}) {
  const [label, setLabel] = useState("")
  const [latitude, setLatitude] = useState("")
  const [longitude, setLongitude] = useState("")
  const [radius, setRadius] = useState("")
  const [units, setUnits] = useState<RadiusUnits>("MILES")
  const parsed = {
    latitude: Number(latitude),
    longitude: Number(longitude),
    radius: Number(radius),
  }
  const valid =
    latitude.trim() !== "" &&
    longitude.trim() !== "" &&
    Math.abs(parsed.latitude) <= 90 &&
    Math.abs(parsed.longitude) <= 180 &&
    parsed.radius > 0
  const field = (
    name: string,
    value: string,
    set: (next: string) => void,
    className: string,
    numeric = true
  ) => (
    <Input
      aria-label={name}
      className={className}
      disabled={disabled}
      {...(numeric ? { inputMode: "decimal" as const } : {})}
      onChange={(event) => {
        set(event.currentTarget.value)
      }}
      placeholder={name}
      value={value}
    />
  )
  return (
    <div className="flex flex-wrap items-center gap-2">
      {field("Place Name", label, setLabel, "w-40", false)}
      {field("Latitude", latitude, setLatitude, "w-28 tabular-nums")}
      {field("Longitude", longitude, setLongitude, "w-28 tabular-nums")}
      {field("Distance", radius, setRadius, "w-24 tabular-nums")}
      <SegmentedChoice
        ariaLabel="New distance units"
        disabled={disabled}
        onChange={setUnits}
        options={UNIT_OPTIONS}
        value={units}
      />
      <Button
        disabled={disabled || !valid}
        onClick={() => {
          onAdd({ ...parsed, bidAdjustment: null, label: label.trim() || null, units })
          setLabel("")
          setLatitude("")
          setLongitude("")
          setRadius("")
        }}
        type="button"
        variant="outline"
      >
        Add Distance
      </Button>
    </div>
  )
}
