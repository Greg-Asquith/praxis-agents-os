// apps/web/src/integrations/meta_ads/components/targeting-edits.tsx

import { TriangleAlertIcon } from "lucide-react"
import type { ReactNode } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Chip,
  ChoiceCards,
  SelectField,
  SwitchField,
  TextField,
} from "@/integrations/meta_ads/components/campaign-controls"
import { ChangeBanner } from "@/integrations/meta_ads/components/change-banner"
import { EntitySearch } from "@/integrations/meta_ads/components/entity-search"
import {
  MetaAdsLink,
  MetaAdsOutcomeTable,
  type MetaAdsOutcomeRow,
} from "@/integrations/meta_ads/components/outcome-table"
import { SettingRow, SettingRows } from "@/integrations/meta_ads/components/setting-rows"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import {
  AGE_OPTIONS,
  GENDER_OPTIONS,
  MAX_AGE_OPTIONS,
  WIDEN_AUDIENCE,
} from "@/integrations/meta_ads/lib/targeting-edit"
import {
  addedByOperator,
  afterEstimate,
  audiencesText,
  currentProblems,
  editSummary,
  editTargeting,
  editValues,
  entryProblem,
  estimateChange,
  estimateText,
  interestsText,
  listHas,
  listState,
  peopleText,
  placesText,
  RESULT_SECTIONS,
  targetingAfter,
  targetingEditRows,
  targetingNotes,
  targetingWarnings,
  widenText,
  withItem,
  withoutItem,
  type ListField,
  type TargetingChip,
  type TargetingEditArgs,
  type TargetingEditChange,
  type TargetingEditResult,
  type TargetingEditRow,
} from "@/integrations/meta_ads/lib/targeting-edits"
import { pluralize } from "@/lib/format"
import { isRecord } from "@/lib/guards"

type Edit = (id: string, change: TargetingEditChange) => void
type SectionProps = { disabled: boolean; edit: Edit; row: TargetingEditRow }

const TOOL = "meta_ads_update_targeting"
const LOCATION_TYPE_OPTIONS = [
  { value: "home_or_recent", label: "People Living There or Recently There" },
  { value: "home", label: "People Living There" },
]

export function TargetingEditApproval({
  args,
  disabled,
  onFieldEdit,
  proposed,
}: {
  args: TargetingEditArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
  proposed: TargetingEditArgs
}) {
  const rows = targetingEditRows(proposed, args)
  const kept = rows.filter((row) => row.included).length
  const edit: Edit = (id, change) => {
    onFieldEdit("changes", editTargeting(rows, id, change))
  }
  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner detail={`${String(kept)} ${pluralize(kept, "ad set")}`} />
      <SettingRows ariaLabel="Ad sets to change" defaultOpen={rows[0]?.edit.id ?? null}>
        {rows.map((row) => (
          <AdSetRow key={row.edit.id} disabled={disabled} edit={edit} row={row} />
        ))}
      </SettingRows>
    </div>
  )
}

function AdSetRow({ disabled, edit, row }: SectionProps) {
  const { edit: adSet, included } = row
  const problems = included
    ? [entryProblem(adSet), ...currentProblems(adSet)].filter((item) => item !== null)
    : []
  const summary = !included ? "Left as it is" : (problems[0] ?? (editSummary(row) || "No changes"))
  const href = adsManagerObjectUrl("adset", adSet.accountId, adSet.id)
  return (
    <SettingRow
      rowKey={adSet.id}
      summary={summary}
      title={adSet.name}
      tone={problems.length > 0 ? "error" : "neutral"}
    >
      <SwitchField
        checked={included}
        disabled={disabled}
        label="Change This Ad Set"
        onChange={(checked) => {
          edit(adSet.id, { included: checked })
        }}
      />
      {included ? (
        <>
          <EstimatedAudience row={row} />
          <Sections disabled={disabled} edit={edit} row={row} />
          {problems.map((problem) => (
            <p key={problem} className="text-destructive text-sm font-medium">
              {problem}
            </p>
          ))}
          {targetingWarnings(adSet).map((warning) => (
            <p key={warning} className="text-warning-text flex items-start gap-2 text-sm">
              <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              {warning}
            </p>
          ))}
          {targetingNotes(adSet).map((note) => (
            <p key={note} className="text-foreground/75 text-sm">
              {note}
            </p>
          ))}
        </>
      ) : null}
      {href ? <MetaAdsLink href={href}>Open in Ads Manager</MetaAdsLink> : null}
    </SettingRow>
  )
}

/** Meta's estimate with the change, its move from now, and the estimate now. */
function EstimatedAudience({ row }: { row: TargetingEditRow }) {
  const check = row.edit.check
  const before = estimateText(check?.estimates.before)
  const after = afterEstimate(row.edit)
  if (!before && !after) return null
  const change = estimateChange(row.edit)
  return (
    <div className="bg-background grid min-w-0 gap-1 rounded-lg border px-3 py-2.5">
      <p className="text-sm font-medium">Estimated Audience</p>
      <p className="flex flex-wrap items-center gap-2 text-lg font-semibold tabular-nums">
        {after ?? "Meta estimates again when you approve"}
        {change ? (
          <Badge variant={change.startsWith("-") ? "secondary" : "success"}>{change}</Badge>
        ) : null}
      </p>
      {before ? <p className="text-muted-foreground text-sm">Current Setting: {before}</p> : null}
    </div>
  )
}

function Sections({ disabled, edit, row }: SectionProps) {
  const adSet = row.edit
  const before = adSet.check?.before ?? {}
  const after = targetingAfter(before, adSet.raw)
  const values = editValues(adSet)
  const unmodelled = adSet.check?.unmodelled ?? {}
  const people = ["age_min", "age_max", "genders"].some((key) => key in values)
  const set = (change: TargetingEditChange) => {
    edit(adSet.id, change)
  }
  return (
    <SettingRows ariaLabel="Targeting" defaultOpen={null}>
      <SettingRow rowKey="locations" summary={placesText(after)} title="Locations">
        {(["locations", "excluded_locations"] as const).map((field) => (
          <ListEditor
            key={field}
            disabled={disabled}
            field={field}
            kept={unmodelled[field]}
            onEntry={(entry) => {
              set({ entry })
            }}
            row={row}
          />
        ))}
        {typeof values.location_types === "string" ? (
          <SelectField
            disabled={disabled}
            label="Who Counts as There"
            onChange={(value) => {
              set({ key: "location_types", value })
            }}
            options={LOCATION_TYPE_OPTIONS}
            value={values.location_types}
          />
        ) : null}
        <CurrentSetting>{placesText(before)}</CurrentSetting>
      </SettingRow>
      {people || unmodelled["ages"] || unmodelled["genders"] ? (
        <SettingRow rowKey="people" summary={peopleText(after)} title="Age and Gender">
          <PeopleFields disabled={disabled} set={set} values={values} />
          <CurrentSetting>{peopleText(before)}</CurrentSetting>
        </SettingRow>
      ) : null}
      {row.chips.length > 0 ? (
        <SettingRow rowKey="interests" summary={interestsText(after)} title="Interests">
          <InterestChips
            chips={row.chips}
            disabled={disabled}
            onToggle={(chip) => {
              set({ chip })
            }}
          />
          <CurrentSetting>{interestsText(before)}</CurrentSetting>
        </SettingRow>
      ) : null}
      <SettingRow rowKey="audiences" summary={audiencesText(after)} title="Audiences">
        {(["audiences", "excluded_audiences"] as const).map((field) => (
          <ListEditor
            key={field}
            disabled={disabled}
            field={field}
            kept={unmodelled[field]}
            onEntry={(entry) => {
              set({ entry })
            }}
            row={row}
          />
        ))}
        <CurrentSetting>{audiencesText(before)}</CurrentSetting>
      </SettingRow>
      {typeof values.advantage_audience === "boolean" ? (
        <SettingRow rowKey="widen" summary={widenText(after)} title="Widen Audience">
          <SwitchField
            checked={values.advantage_audience}
            description={WIDEN_AUDIENCE.description}
            disabled={disabled}
            label={WIDEN_AUDIENCE.label}
            onChange={(value) => {
              set({ key: "advantage_audience", value })
            }}
          />
          <CurrentSetting>{widenText(before)}</CurrentSetting>
        </SettingRow>
      ) : null}
      {"eu_payer" in values || "eu_beneficiary" in values ? (
        <SettingRow
          rowKey="eu"
          summary={[values.eu_payer, values.eu_beneficiary].filter(Boolean).join(" · ")}
          title="EU Transparency"
        >
          <div className="grid min-w-0 gap-3 sm:grid-cols-2">
            {(["eu_payer", "eu_beneficiary"] as const).map((key) =>
              typeof values[key] === "string" ? (
                <TextField
                  key={key}
                  disabled={disabled}
                  label={key === "eu_payer" ? "Who Pays for the Ads" : "Who the Ads Benefit"}
                  onChange={(value) => {
                    set({ key, value })
                  }}
                  value={values[key]}
                />
              ) : null
            )}
          </div>
        </SettingRow>
      ) : null}
    </SettingRows>
  )
}

function CurrentSetting({ children }: { children: ReactNode }) {
  return <p className="text-muted-foreground text-sm">Current Setting: {children}</p>
}

const LIST_COPY: Record<
  ListField,
  { title: string; search: string; placeholder: string; entityKind: string }
> = {
  locations: {
    title: "In These Places",
    search: "Add a Location",
    placeholder: "Search for a country, region, or city",
    entityKind: "meta_ads_targeting_location",
  },
  excluded_locations: {
    title: "Not in These Places",
    search: "Exclude a Location",
    placeholder: "Search for a country, region, or city",
    entityKind: "meta_ads_targeting_location",
  },
  audiences: {
    title: "In These Audiences",
    search: "Add an Audience",
    placeholder: "Search your saved audiences",
    entityKind: "meta_ads_audience",
  },
  excluded_audiences: {
    title: "Not in These Audiences",
    search: "Exclude an Audience",
    placeholder: "Search your saved audiences",
    entityKind: "meta_ads_audience",
  },
}

/** One place or audience list: chips to remove, removals to undo, and a search to add. */
function ListEditor({
  disabled,
  field,
  kept,
  onEntry,
  row,
}: {
  disabled: boolean
  field: ListField
  // What the list holds that Praxis keeps as it is; set when it can't change here.
  kept: string | undefined
  onEntry: (entry: Record<string, unknown>) => void
  row: TargetingEditRow
}) {
  const copy = LIST_COPY[field]
  const state = listState(row, field)
  const entry = row.edit.raw
  return (
    <div className="grid min-w-0 gap-2">
      <p className="text-sm font-medium">{copy.title}</p>
      {kept ? (
        <p className="text-foreground/75 text-sm">
          This ad set's list includes {kept}, so change it in Ads Manager.
        </p>
      ) : (
        <>
          {state.items.length > 0 ? (
            <div className="flex min-w-0 flex-wrap gap-2">
              {state.items.map((item) => (
                <Chip
                  key={item.id}
                  detail={
                    [
                      item.detail,
                      item.added
                        ? addedByOperator(row, field, item)
                          ? "Added by You"
                          : "Added"
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" · ") || null
                  }
                  disabled={disabled}
                  label={item.added ? `+${item.label}` : item.label}
                  onRemove={() => {
                    onEntry(withoutItem(entry, field, item))
                  }}
                />
              ))}
            </div>
          ) : null}
          <UndoLine
            action="Keep"
            disabled={disabled}
            items={state.removing}
            onUndo={(item) => {
              onEntry(withItem(entry, field, item.item))
            }}
            title="Removing"
          />
          <UndoLine
            action="Restore"
            disabled={disabled}
            items={state.leftOut}
            onUndo={(item) => {
              onEntry(withItem(entry, field, item.item))
            }}
            title="Left Out"
          />
          <EntitySearch
            disabled={disabled}
            entityKind={copy.entityKind}
            fieldKey="changes"
            isTaken={({ value }) => isRecord(value) && listHas(state, field, value)}
            label={copy.search}
            onChoose={({ value }) => {
              if (isRecord(value)) onEntry(withItem(entry, field, value))
            }}
            placeholder={copy.placeholder}
            searchRequired={field.endsWith("locations")}
            toolName={TOOL}
          />
        </>
      )}
    </div>
  )
}

function UndoLine<T extends { id: string; label: string }>({
  action,
  disabled,
  items,
  onUndo,
  title,
}: {
  action: string
  disabled: boolean
  items: readonly T[]
  onUndo: (item: T) => void
  title: string
}) {
  if (items.length === 0) return null
  return (
    <div className="text-muted-foreground flex min-w-0 flex-wrap items-center gap-2 text-sm">
      <span>{title}:</span>
      {items.map((item) => (
        <span key={item.id} className="inline-flex items-center gap-1">
          <span className="line-through">{item.label}</span>
          <Button
            aria-label={`${action} ${item.label}`}
            disabled={disabled}
            onClick={() => {
              onUndo(item)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            {action}
          </Button>
        </span>
      ))}
    </div>
  )
}

function PeopleFields({
  disabled,
  set,
  values,
}: {
  disabled: boolean
  set: (change: TargetingEditChange) => void
  values: ReturnType<typeof editValues>
}) {
  const { age_min: min, age_max: max, genders } = values
  return (
    <>
      {min !== undefined || max !== undefined ? (
        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
          {min !== undefined ? (
            <SelectField
              disabled={disabled}
              label="Minimum Age"
              onChange={(age) => {
                set({ key: "age_min", value: Number(age) })
              }}
              options={AGE_OPTIONS}
              value={String(min)}
            />
          ) : null}
          {max !== undefined ? (
            <SelectField
              disabled={disabled}
              label="Maximum Age"
              onChange={(age) => {
                set({ key: "age_max", value: age === "65+" ? "none" : Number(age) })
              }}
              options={MAX_AGE_OPTIONS}
              value={max === "none" ? "65+" : String(max)}
            />
          ) : null}
        </div>
      ) : null}
      {typeof genders === "string" ? (
        <ChoiceCards
          ariaLabel="Gender"
          columns={3}
          disabled={disabled}
          onChange={(value) => {
            set({ key: "genders", value })
          }}
          options={GENDER_OPTIONS}
          value={genders}
        />
      ) : null}
    </>
  )
}

/** Each proposed interest or language change; pressing one drops it, and again restores it. */
function InterestChips({
  chips,
  disabled,
  onToggle,
}: {
  chips: readonly TargetingChip[]
  disabled: boolean
  onToggle: (chip: TargetingChip) => void
}) {
  const kept = chips.filter((chip) => chip.included)
  const dropped = chips.filter((chip) => !chip.included)
  return (
    <>
      {kept.length > 0 ? (
        <div className="flex min-w-0 flex-wrap gap-2">
          {kept.map((chip) => (
            <Chip
              key={`${chip.kind}:${chip.id}`}
              disabled={disabled}
              label={chip.label}
              onRemove={() => {
                onToggle(chip)
              }}
            />
          ))}
        </div>
      ) : null}
      <UndoLine
        action="Restore"
        disabled={disabled}
        items={dropped.map((chip) => ({ id: `${chip.kind}:${chip.id}`, label: chip.label, chip }))}
        onUndo={(item) => {
          onToggle(item.chip)
        }}
        title="Left Out"
      />
    </>
  )
}

export function TargetingEditOutcome({ result }: { result: TargetingEditResult }) {
  const rows: MetaAdsOutcomeRow[] = result.adSets.flatMap((adSet) => {
    const sections = [...new Set(adSet.sections.map((key) => RESULT_SECTIONS[key]))].filter(
      (section) => section !== undefined
    )
    return sections.map((section, index) => ({
      name: adSet.name,
      setting: section.title,
      before: section.text(adSet.before),
      after:
        adSet.outcome === "failed" || adSet.outcome === "unverified"
          ? "—"
          : section.text(adSet.requested),
      outcome: adSet.outcome,
      // The ad set's message once, on its first setting.
      details: index === 0 ? (adSet.message ?? "") : "",
      errorCode: index === 0 ? adSet.errorCode : null,
    }))
  })
  return (
    <MetaAdsOutcomeTable
      columns={[
        { key: "name", kind: "text", label: "Ad Set" },
        { key: "setting", kind: "text", label: "Setting" },
        { key: "before", kind: "text", label: "Before" },
        { key: "after", kind: "text", label: "After" },
      ]}
      exportFilename="meta-ads-targeting-changes.csv"
      rows={rows}
    />
  )
}
