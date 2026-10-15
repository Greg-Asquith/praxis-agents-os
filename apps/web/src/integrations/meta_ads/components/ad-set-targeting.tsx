// apps/web/src/integrations/meta_ads/components/ad-set-targeting.tsx

import {
  Chip,
  ChoiceCards,
  SelectField,
  SwitchField,
} from "@/integrations/meta_ads/components/campaign-controls"
import { EntitySearch } from "@/integrations/meta_ads/components/entity-search"
import type { CreateAdSetArgs } from "@/integrations/meta_ads/lib/create-ad-set"
import {
  addAudience,
  addInterest,
  addLocation,
  detailedGroups,
  itemName,
  removeDetailed,
  removeItem,
  targetingItems,
} from "@/integrations/meta_ads/lib/targeting-edit"
import { TARGETING_KIND_LABELS } from "@/integrations/meta_ads/lib/targeting"

type TargetingProps = {
  args: CreateAdSetArgs
  disabled: boolean
  onTargeting: (targeting: Record<string, unknown>) => void
}

const TOOL = "meta_ads_create_ad_set"
const AGES = Array.from({ length: 53 }, (_, index) => {
  const age = String(index + 13)
  return { value: age, label: age }
})
const MAX_AGES = [{ value: "65+", label: "65+" }, ...AGES]
const GENDER_OPTIONS = [
  { value: "all", label: "All" },
  { value: "men", label: "Men" },
  { value: "women", label: "Women" },
]

function chipItems(
  items: Record<string, unknown>[],
  disabled: boolean,
  onRemove: (index: number) => void,
  prefix = ""
) {
  return items.map((item, index) => (
    <Chip
      detail={TARGETING_KIND_LABELS[String(item["kind"])] ?? null}
      disabled={disabled}
      key={`${prefix}${String(item["kind"])}-${String(item["key"] ?? item["audience_id"])}`}
      label={itemName(item)}
      onRemove={() => {
        onRemove(index)
      }}
    />
  ))
}

export function AdSetLocations({ args, disabled, onTargeting }: TargetingProps) {
  const { targeting } = args
  return (
    <>
      <div className="flex min-w-0 flex-wrap gap-2">
        {chipItems(targetingItems(targeting["locations"]), disabled, (index) => {
          onTargeting(removeItem(targeting, "locations", index))
        })}
        {targetingItems(targeting["excluded_locations"]).map((item, index) => (
          <span
            className="inline-flex items-center gap-1.5 text-sm"
            key={`not-${String(item["key"])}`}
          >
            <span className="text-foreground/75">Not in</span>
            <Chip
              disabled={disabled}
              label={itemName(item)}
              onRemove={() => {
                onTargeting(removeItem(targeting, "excluded_locations", index))
              }}
            />
          </span>
        ))}
      </div>
      <EntitySearch
        disabled={disabled}
        entityKind="meta_ads_targeting_location"
        fieldKey="targeting"
        isTaken={({ value }) => addLocation(targeting, "locations", value) === targeting}
        label="Add a Location"
        onChoose={({ value }) => {
          onTargeting(addLocation(targeting, "locations", value))
        }}
        placeholder="Search for a country, region, or city"
        searchRequired
        toolName={TOOL}
      />
    </>
  )
}

export function AdSetPeople({ args, disabled, onTargeting }: TargetingProps) {
  const { targeting } = args
  if (args.specialCategory)
    return (
      <p className="text-foreground/75 text-sm">
        This campaign has a special ad category, so Meta reaches ages 18 to 65+ and all genders.
      </p>
    )
  const min = typeof targeting["age_min"] === "number" ? targeting["age_min"] : 18
  const max = typeof targeting["age_max"] === "number" ? targeting["age_max"] : null
  return (
    <>
      <div className="grid min-w-0 gap-3 sm:grid-cols-2">
        <SelectField
          disabled={disabled}
          label="Minimum Age"
          onChange={(age) => {
            onTargeting({ ...targeting, age_min: Number(age), age_max: max })
          }}
          options={AGES}
          value={String(min)}
        />
        <SelectField
          disabled={disabled}
          label="Maximum Age"
          onChange={(age) => {
            onTargeting({ ...targeting, age_min: min, age_max: age === "65+" ? null : Number(age) })
          }}
          options={MAX_AGES}
          value={max === null ? "65+" : String(max)}
        />
      </div>
      <ChoiceCards
        ariaLabel="Gender"
        columns={3}
        disabled={disabled}
        onChange={(genders) => {
          onTargeting({ ...targeting, genders })
        }}
        options={GENDER_OPTIONS}
        value={typeof targeting["genders"] === "string" ? targeting["genders"] : "all"}
      />
    </>
  )
}

export function AdSetInterests({ args, disabled, onTargeting }: TargetingProps) {
  const { targeting } = args
  const groups = detailedGroups(targeting)
  const audiences = targetingItems(targeting["audiences"])
  const excluded = targetingItems(targeting["excluded_audiences"])
  return (
    <>
      {groups.map((group, groupIndex) => (
        <div
          className="grid min-w-0 gap-1.5"
          key={group.map((item) => String(item["key"])).join("-")}
        >
          {groupIndex > 0 ? (
            <p className="text-foreground/75 text-sm">And must also match one of:</p>
          ) : null}
          <div className="flex min-w-0 flex-wrap gap-2">
            {chipItems(group, disabled, (index) => {
              onTargeting(removeDetailed(targeting, groupIndex, index))
            })}
          </div>
        </div>
      ))}
      <EntitySearch
        disabled={disabled}
        entityKind="meta_ads_targeting_interest"
        fieldKey="targeting"
        isTaken={({ value }) => addInterest(targeting, value) === targeting}
        label="Add an Interest"
        onChoose={({ value }) => {
          onTargeting(addInterest(targeting, value))
        }}
        placeholder="Search interests"
        searchRequired
        toolName={TOOL}
      />
      {audiences.length > 0 ? (
        <div className="flex min-w-0 flex-wrap gap-2">
          {chipItems(audiences, disabled, (index) => {
            onTargeting(removeItem(targeting, "audiences", index))
          })}
        </div>
      ) : null}
      <EntitySearch
        disabled={disabled}
        entityKind="meta_ads_audience"
        fieldKey="targeting"
        isTaken={({ value }) => addAudience(targeting, "audiences", value) === targeting}
        label="Add an Audience"
        onChoose={({ value }) => {
          onTargeting(addAudience(targeting, "audiences", value))
        }}
        placeholder="Search your saved audiences"
        toolName={TOOL}
      />
      {excluded.length > 0 ? (
        <div className="grid min-w-0 gap-1.5">
          <p className="text-foreground/75 text-sm">Not in these audiences:</p>
          <div className="flex min-w-0 flex-wrap gap-2">
            {chipItems(
              excluded,
              disabled,
              (index) => {
                onTargeting(removeItem(targeting, "excluded_audiences", index))
              },
              "not-"
            )}
          </div>
        </div>
      ) : null}
      <SwitchField
        checked={targeting["advantage_audience"] !== false}
        description="Meta may show the ads to people outside your interests, ages, and genders when it expects better results."
        disabled={disabled}
        label="Let Meta Widen the Audience"
        onChange={(on) => {
          onTargeting({ ...targeting, advantage_audience: on })
        }}
      />
    </>
  )
}
