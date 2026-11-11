// apps/web/src/integrations/google_ads/components/targeting-approval.tsx

import { InfoIcon, PlusIcon, XIcon } from "lucide-react"
import { useMemo, useState, type ReactNode } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { DataColumn } from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { SegmentedChoice } from "@/integrations/ads/components/controls"
import { EntitySearch } from "@/integrations/ads/components/entity-search"
import { ParentTable, type ParentRow } from "@/integrations/ads/components/parent-table"
import { SettingRow, SettingRows } from "@/integrations/ads/components/setting-rows"
import type { EntityChoice } from "@/features/tools/types"
import {
  ScheduleGrid,
  ScheduleWindows,
} from "@/integrations/google_ads/components/ad-schedule-editor"
import { BidAdjustment } from "@/integrations/google_ads/components/bid-adjustment"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { DeviceAdjustments } from "@/integrations/google_ads/components/device-adjustments"
import {
  AudienceRows,
  DemographicAdjustments,
} from "@/integrations/google_ads/components/targeting-audiences"
import { DIMENSION_NAMES } from "@/integrations/google_ads/lib/demographics"
import {
  addAudience,
  cancelAudience,
  changedDimensions,
  changesAudiences,
  clearAudiences,
  clearDemographics,
  demographicLines,
  setAudienceBid,
  setAudienceMode,
  setDemographic,
} from "@/integrations/google_ads/lib/targeting-audiences"
import { ALL_WEEK, type ScheduleWindow } from "@/integrations/google_ads/lib/ad-schedule"
import { LocationPaste } from "@/integrations/google_ads/components/location-paste"
import { LOCATION_SETTING_LABELS } from "@/integrations/google_ads/lib/update-targeting-result"
import {
  acceptsLanguageAdds,
  addTarget,
  campaignRows,
  campaignsByDifference,
  campaignsOn,
  changesPlaces,
  clearDevices,
  clearedChange,
  deviceLines,
  editInScope,
  editRadius,
  entryNoun,
  entryPlural,
  itemCount,
  keepRadius,
  languagesText,
  liveSchedule,
  liveScheduleText,
  needsCheck,
  parseCancelled,
  radiusIdentity,
  radiusLines,
  radiusRemovals,
  radiusText,
  removeTarget,
  requestedSchedule,
  schedulesValid,
  scopedArgs,
  serializeChanges,
  setBidAdjustment,
  setDevice,
  setLocationSetting,
  setSchedule,
  shownLocationSetting,
  targetingCounts,
  targetingNotes,
  targetLines,
  unchangedLanguages,
  unchangedPlaces,
  unchangedRadius,
  whatChanges,
  type AudienceKind,
  type AudienceMode,
  type CampaignRow,
  type DemographicDimension,
  type LocationSetting,
  type RadiusTarget,
  type RadiusUnits,
  type ScheduleRequest,
  type Target,
  type TargetField,
  type TargetingChange,
  type TargetLine,
  type UpdateTargetingArgs,
} from "@/integrations/google_ads/lib/update-targeting"

const TOOL = "google_ads_update_targeting"
// More places of one type than this collapse to one row with a Review control.
const GROUP_FROM = 8
// How many unchanged places the card lists before trimming.
const MAX_UNCHANGED = 5

const PARENT_COLUMNS: DataColumn[] = [
  { key: "changes", kind: "number", label: "Changes", width: 100 },
  { key: "what", kind: "text", label: "What Changes", width: 180 },
  { key: "languages", kind: "text", label: "Languages", width: 160 },
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

const DIMENSION_OPTIONS = (Object.keys(DIMENSION_NAMES) as DemographicDimension[]).map((value) => ({
  label: DIMENSION_NAMES[value],
  value,
}))

function audienceOf(choice: EntityChoice) {
  const { key, kind, name } = choice.value
  if (typeof key !== "string" || typeof kind !== "string") return null
  return {
    bidAdjustment: null,
    key,
    kind: kind as AudienceKind,
    name: typeof name === "string" ? name : choice.label,
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
  const [chosen, setChosen] = useState<string | null>(null)
  // Places stay behind More Settings when the request only changes devices or the schedule.
  const [showPlaces, setShowPlaces] = useState(false)
  const [showAudiences, setShowAudiences] = useState(false)
  const [dimension, setDimension] = useState<DemographicDimension>("AGE_RANGE")
  const cancelled = useMemo(() => parseCancelled(controls.retained), [controls.retained])
  const rows = useMemo(() => campaignRows(args, checked, cancelled), [args, checked, cancelled])
  const counts = targetingCounts(rows)
  const many = rows.length > 1
  // A click on a campaign shows and edits only its changes; none shows them across every campaign.
  const open = rows.find((row) => row.key === chosen) ?? null
  const scope = open?.key ?? null
  const shown = useMemo(() => scopedArgs(args, scope), [args, scope])
  const lines = useMemo(() => targetLines(shown), [shown])
  const parents = useMemo(() => campaignsByDifference(rows).map(parentRow), [rows])
  // With one campaign there's no table, so its problems show without a click.
  const problemRow = open ?? (many ? null : rows[0])
  const schedule = requestedSchedule(shown)
  const noun = entryNoun(args.changes.length > 0 ? args : { changes: cancelled })
  // Ad groups take audiences and demographics only, so campaign settings show for campaigns.
  const campaignsShown = shown.changes.some((change) => change.level === "campaign")
  const devicesOn = shown.changes.some((change) => change.devices.length > 0)
  const audiencesOn = showAudiences || shown.changes.some(changesAudiences)
  const dimensions = changedDimensions(shown)
  // More Settings offers the dimensions the request doesn't change yet.
  const otherDimensions = DIMENSION_OPTIONS.filter((option) => !dimensions.includes(option.value))
  const other = dimensions.includes(dimension)
    ? (otherDimensions[0]?.value ?? dimension)
    : dimension
  const placesOn =
    campaignsShown &&
    (showPlaces ||
      shown.changes.some(changesPlaces) ||
      (!devicesOn && schedule.kind === "none" && !audiencesOn && dimensions.length === 0))
  const notes = targetingNotes(shown)
  // Campaigns in different time zones have no single zone the times can be read in.
  const timeZones = new Set(
    shown.changes.map((change) => args.accounts.get(change.key.split("/")[1] ?? "")?.timeZone)
  )
  const [timeZone] = timeZones.size === 1 ? timeZones : []
  const live = liveSchedule(shown)

  // A campaign left with nothing leaves the request, and stays beside it so Undo can restore it.
  const save = (next: readonly TargetingChange[]) => {
    const kept = new Set(next.map((change) => change.key))
    const dropped = args.changes.filter((change) => !kept.has(change.key))
    const restored = cancelled.filter((change) => !kept.has(change.key))
    if (dropped.length > 0 || restored.length !== cancelled.length)
      controls.onRetain?.(serializeChanges([...restored, ...dropped]))
    onFieldEdit("changes", serializeChanges(next))
  }
  const edit = (change: (changes: readonly TargetingChange[]) => TargetingChange[]) => {
    save(editInScope(args.changes, scope, change))
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
    save(
      editInScope(addable(), scope, (changes) => {
        let next: TargetingChange[] = [...changes]
        for (const choice of choices) {
          const target = targetOf(choice)
          if (target) {
            next = addTarget(next, field, target, (change) =>
              field === "add_languages" ? acceptsLanguageAdds(args, change) : true
            )
          }
        }
        return next
      })
    )
  }
  const setDemographicValue = (
    dimension: DemographicDimension,
    value: string,
    next: Parameters<typeof setDemographic>[3]
  ) => {
    save(
      editInScope(addable(), scope, (changes) => setDemographic(changes, dimension, value, next))
    )
  }
  const removeMany = (field: TargetField, keys: readonly string[]) => {
    edit((changes) => {
      let next: TargetingChange[] = [...changes]
      for (const key of keys) next = removeTarget(next, field, key)
      return next
    })
  }

  return (
    <div className="grid min-w-0 gap-3">
      <StatusNote args={args} noun={noun} />
      {many ? (
        <AttentionLine
          count={counts.problems}
          onShow={() => {
            setChosen(rows.find((row) => row.problems.length > 0 && !row.cancelled)?.key ?? null)
          }}
        />
      ) : null}
      {many ? (
        <ParentTable
          columns={
            // Languages only matter when a campaign holds or changes one.
            parents.some((row) => row.values["languages"] !== "—")
              ? PARENT_COLUMNS
              : PARENT_COLUMNS.filter((column) => column.key !== "languages")
          }
          disabled={disabled}
          label={
            noun === "item"
              ? "Campaigns and Ad Groups"
              : noun === "ad group"
                ? "Ad Groups"
                : "Campaigns"
          }
          onCancel={cancelCampaign}
          onSelect={setChosen}
          onUndo={undo}
          renderCell={(column, row) => {
            const value = row.values[column.key]
            return typeof value === "string" ? (
              <span className="text-sm wrap-anywhere whitespace-normal">{value}</span>
            ) : null
          }}
          rowNoun={[noun, entryPlural(noun)]}
          rows={parents}
          selected={scope}
        />
      ) : null}
      {open?.cancelled || (!many && counts.total === 0 && rows[0]) ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2">
          <p className="text-muted-foreground text-sm">
            {open
              ? `${open.name} is cancelled, so its targeting won't change.`
              : "Nothing is left to change."}
          </p>
          <Button
            disabled={disabled}
            onClick={() => {
              undo(open?.key ?? rows[0]?.key ?? "")
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            Undo
          </Button>
        </div>
      ) : (
        <>
          {problemRow && problemRow.problems.length > 0 ? (
            <CampaignProblems row={problemRow} />
          ) : null}
          {notes.map((note) => (
            <p
              key={note}
              className="bg-warning/10 text-warning-text flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm"
            >
              <InfoIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              {note}
            </p>
          ))}
          {schedule.kind === "none" ? null : (
            <section aria-label="Ad schedule" className="overflow-hidden rounded-lg border">
              <SectionHeading
                detail={timeZone ? `Times are in ${timeZone}` : null}
                disabled={disabled}
                onCancel={() => {
                  edit((changes) => setSchedule(changes, null))
                }}
                title="Ad Schedule"
              />
              <ScheduleBody
                disabled={disabled}
                live={live}
                onChange={(next) => {
                  edit((changes) => setSchedule(changes, next))
                }}
                request={schedule}
              />
            </section>
          )}
          {devicesOn ? (
            <section aria-label="Devices" className="overflow-hidden rounded-lg border">
              <SectionHeading
                disabled={disabled}
                onCancel={() => {
                  edit(clearDevices)
                }}
                title="Devices"
              />
              <DeviceAdjustments
                disabled={disabled}
                lines={deviceLines(shown)}
                onChange={(device, next) => {
                  save(editInScope(addable(), scope, (changes) => setDevice(changes, device, next)))
                }}
              />
            </section>
          ) : null}
          {audiencesOn ? (
            <section aria-label="Audiences" className="overflow-hidden rounded-lg border">
              <SectionHeading
                disabled={disabled}
                onCancel={() => {
                  setShowAudiences(false)
                  edit(clearAudiences)
                }}
                title="Audiences"
              />
              <AudienceRows
                args={shown}
                disabled={disabled}
                noun={noun}
                onAdd={(choice) => {
                  const target = audienceOf(choice)
                  if (target)
                    save(editInScope(addable(), scope, (changes) => addAudience(changes, target)))
                }}
                onBid={(id, bid) => {
                  edit((changes) => setAudienceBid(changes, id, bid))
                }}
                onCancel={(field, id) => {
                  edit((changes) => cancelAudience(changes, field, id))
                }}
                onMode={(mode: AudienceMode | null) => {
                  save(editInScope(addable(), scope, (changes) => setAudienceMode(changes, mode)))
                }}
              />
            </section>
          ) : null}
          {dimensions.map((item) => (
            <section
              key={item}
              aria-label={DIMENSION_NAMES[item]}
              className="overflow-hidden rounded-lg border"
            >
              <SectionHeading
                disabled={disabled}
                onCancel={() => {
                  edit((changes) => clearDemographics(changes, item))
                }}
                title={DIMENSION_NAMES[item]}
              />
              <DemographicAdjustments
                disabled={disabled}
                lines={demographicLines(shown, item)}
                onChange={(value, next) => {
                  setDemographicValue(item, value, next)
                }}
              />
            </section>
          ))}
          {placesOn ? (
            <>
              <section
                aria-label="Where ads can show"
                className="overflow-hidden rounded-lg border"
              >
                <h4 className="bg-muted/40 border-b px-3 py-2 text-sm font-semibold">
                  Where Ads Can Show
                </h4>
                <div className="divide-y">
                  <LocationRows
                    args={shown}
                    disabled={disabled}
                    lines={lines}
                    many={shown.changes.length > 1}
                    onBid={(key, bid) => {
                      edit((changes) => setBidAdjustment(changes, new Set([key]), bid))
                    }}
                    onCancel={removeMany}
                    onKeepRadius={(id) => {
                      edit((changes) => keepRadius(changes, id))
                    }}
                    onRadius={(identity, next) => {
                      edit((changes) => editRadius(changes, identity, next))
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
                        save(
                          editInScope(addable(), scope, (changes) =>
                            editRadius(changes, null, target)
                          )
                        )
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
                args={shown}
                disabled={disabled}
                lines={lines}
                many={shown.changes.length > 1}
                onAdd={(choice) => {
                  addTargets("add_languages", [choice])
                }}
                onCancel={removeMany}
              />
            </>
          ) : null}
          <SettingRows ariaLabel="More settings" defaultOpen={null}>
            {audiencesOn ? null : (
              <SettingRow rowKey="audiences" summary="No change" title="Audiences">
                <Button
                  className="w-fit"
                  disabled={disabled}
                  onClick={() => {
                    setShowAudiences(true)
                  }}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  Change Audiences
                </Button>
              </SettingRow>
            )}
            {otherDimensions.length === 0 ? null : (
              <SettingRow
                rowKey="demographics"
                summary={dimensions.length > 0 ? "Other groups: no change" : "No change"}
                title="Demographics"
              >
                <SegmentedChoice
                  ariaLabel="Which demographic to change"
                  disabled={disabled}
                  onChange={setDimension}
                  options={otherDimensions}
                  value={other}
                />
                <DemographicAdjustments
                  disabled={disabled}
                  lines={demographicLines(shown, other)}
                  onChange={(value, next) => {
                    setDemographicValue(other, value, next)
                  }}
                />
              </SettingRow>
            )}
            {placesOn || !campaignsShown ? null : (
              <SettingRow rowKey="places" summary="No change" title="Locations">
                <Button
                  className="w-fit"
                  disabled={disabled}
                  onClick={() => {
                    setShowPlaces(true)
                  }}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  Change Locations or Languages
                </Button>
              </SettingRow>
            )}
            {schedule.kind === "none" && campaignsShown ? (
              <SettingRow rowKey="schedule" summary={liveScheduleText(shown)} title="Ad Schedule">
                {live === null && shown.changes.length > 1 ? (
                  // A shared starting week would replace each campaign's own schedule.
                  <p className="text-sm">Choose a campaign above to change its schedule.</p>
                ) : (
                  <Button
                    className="w-fit"
                    disabled={disabled}
                    onClick={() => {
                      save(
                        editInScope(addable(), scope, (changes) =>
                          setSchedule(changes, startingWeek(live))
                        )
                      )
                    }}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    Change the Schedule
                  </Button>
                )}
              </SettingRow>
            ) : null}
            {devicesOn || !campaignsShown ? null : (
              <SettingRow rowKey="devices" summary="No change" title="Devices">
                <DeviceAdjustments
                  disabled={disabled}
                  lines={deviceLines(shown)}
                  onChange={(device, next) => {
                    save(
                      editInScope(addable(), scope, (changes) => setDevice(changes, device, next))
                    )
                  }}
                />
              </SettingRow>
            )}
            {placesOn ? (
              <SettingRow
                rowKey="location-setting"
                summary={settingSummary(shown)}
                title="Who Counts"
              >
                <SegmentedChoice
                  ariaLabel="Who counts as being in these places"
                  disabled={disabled}
                  onChange={(value: LocationSetting) => {
                    edit((changes) => setLocationSetting(changes, value))
                  }}
                  options={SETTING_OPTIONS}
                  value={shownLocationSetting(shown)}
                />
                {shown.changes.some((change) => change.setting !== null) ? (
                  <Button
                    className="w-fit"
                    disabled={disabled}
                    onClick={() => {
                      edit((changes) => setLocationSetting(changes, null))
                    }}
                    size="sm"
                    type="button"
                    variant="ghost"
                  >
                    Cancel This Change
                  </Button>
                ) : null}
              </SettingRow>
            ) : null}
          </SettingRows>
        </>
      )}
      {needsCheck(args, checked) && args.changes.length > 0 ? (
        <CheckChanges
          disabled={disabled}
          canCheck={schedulesValid(args)}
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

function SectionHeading({
  detail = null,
  disabled,
  onCancel,
  title,
}: {
  detail?: string | null
  disabled: boolean
  onCancel: () => void
  title: string
}) {
  return (
    <div className="bg-muted/40 flex min-w-0 items-center gap-2 border-b py-1 pr-1.5 pl-3">
      <h4 className="text-sm font-semibold">{title}</h4>
      {detail ? <span className="text-muted-foreground text-xs">{detail}</span> : null}
      <Button
        className="ml-auto"
        disabled={disabled}
        onClick={onCancel}
        size="sm"
        type="button"
        variant="ghost"
      >
        Cancel This Change
      </Button>
    </div>
  )
}

/** The live week to edit from, or every hour of every day when ads run at any time. */
function startingWeek(live: readonly ScheduleWindow[] | null): ScheduleWindow[] {
  return [...(live && live.length > 0 ? live : ALL_WEEK)]
}

/** Now as a line, and After as a grid with its windows, or why there's nothing to edit here. */
function ScheduleBody({
  disabled,
  live,
  onChange,
  request,
}: {
  disabled: boolean
  // The week every shown campaign runs on now, or null when they differ.
  live: ScheduleWindow[] | null
  onChange: (next: ScheduleWindow[] | "clear") => void
  request: ScheduleRequest
}) {
  const now = live ? (
    <ScheduleGrid label="Now" windows={live} />
  ) : (
    <p className="text-sm">
      <span className="font-medium">Now:</span>{" "}
      <span className="text-muted-foreground">Differs by campaign</span>
    </p>
  )
  return (
    <div className="grid min-w-0 gap-3 p-3">
      {request.kind === "varies" ? (
        <>
          {now}
          <p className="text-sm">
            Each campaign gets its own schedule. Choose a campaign above to see or change it.
          </p>
        </>
      ) : request.kind === "clear" ? (
        <>
          <div className="grid min-w-0 gap-4 md:grid-cols-2">
            {now}
            <ScheduleGrid label="After" windows={[]} />
          </div>
          <Button
            className="w-fit"
            disabled={disabled}
            onClick={() => {
              onChange(startingWeek(live))
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            Choose Times Instead
          </Button>
        </>
      ) : request.kind === "set" ? (
        <>
          <div className="grid min-w-0 gap-4 md:grid-cols-2">
            {now}
            <ScheduleGrid label="After" windows={request.windows} />
          </div>
          <ScheduleWindows disabled={disabled} onChange={onChange} windows={request.windows} />
          <Button
            className="w-fit"
            disabled={disabled}
            onClick={() => {
              onChange("clear")
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            Show Ads at Any Time
          </Button>
        </>
      ) : null}
    </div>
  )
}

function parentRow(row: CampaignRow): ParentRow {
  const check = row.check && !row.check.unavailable ? row.check : null
  return {
    cancelled: row.cancelled,
    context: check?.campaignName ?? null,
    key: row.key,
    name: row.name,
    problems: row.problems.length,
    values: {
      changes: row.cancelled ? 0 : itemCount(row.change),
      languages: languagesText(row.change, row.check),
      what: row.cancelled
        ? "Left as it is"
        : row.alreadySet
          ? "Already set"
          : whatChanges(row.change),
    },
  }
}

function settingSummary(args: UpdateTargetingArgs): string {
  const shown = `${LOCATION_SETTING_LABELS[shownLocationSetting(args)] ?? "People in"} these places`
  return args.changes.some((change) => change.setting !== null) ? `Changing to: ${shown}` : shown
}

/** States what approving does now: a paused campaign shows no ads until someone turns it on. */
function StatusNote({ args, noun }: { args: UpdateTargetingArgs; noun: string }) {
  const total = args.changes.length
  if (total === 0) return null
  const on = campaignsOn(args)
  const many = entryPlural(noun)
  if (on === 0)
    return (
      <p className="bg-muted text-foreground/80 flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm">
        <InfoIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        {total === 1
          ? `This ${noun} is paused, so these changes won't affect its ads until it's turned on.`
          : `These ${many} are paused, so these changes won't affect their ads until they're turned on.`}
      </p>
    )
  const detail =
    on === null
      ? `${String(total)} ${total === 1 ? noun : many}`
      : total === 1
        ? `This ${noun} is on.`
        : `${String(on)} of ${String(total)} ${many} are on.`
  return <ChangeBanner detail={detail} />
}

/** Why Google turned down the shown campaign's changes. */
function CampaignProblems({ row }: { row: CampaignRow }) {
  return (
    <div
      className="border-destructive/30 bg-destructive/5 grid min-w-0 gap-0.5 rounded-lg border px-3 py-2 text-sm"
      role="alert"
    >
      <span className="font-medium wrap-anywhere">{row.name} Needs Attention</span>
      {row.problems.map((problem) => (
        <span key={problem} className="text-destructive wrap-anywhere">
          {problem}
        </span>
      ))}
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
      title="Cancel This Change"
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
          if (Number.isFinite(radius) && radius > 0 && radius !== target.radius) {
            onChange({ ...target, radius })
          }
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
            fieldKey="changes"
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
    Number.isFinite(parsed.radius) &&
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
