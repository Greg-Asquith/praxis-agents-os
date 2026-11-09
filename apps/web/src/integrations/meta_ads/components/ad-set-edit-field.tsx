// apps/web/src/integrations/meta_ads/components/ad-set-edit-field.tsx

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { AdScheduleField } from "@/integrations/meta_ads/components/ad-schedule"
import {
  AttributionField,
  FrequencyField,
} from "@/integrations/meta_ads/components/ad-set-delivery-fields"
import { EntityPicker } from "@/integrations/ads/components/entity-picker"
import { SelectField, TextField } from "@/integrations/ads/components/controls"
import { MoneyField } from "@/integrations/ads/components/money-field"
import { fromText, parseAdSchedule } from "@/integrations/meta_ads/lib/ad-set-delivery"
import {
  ASSET_SETTINGS,
  currentSetting,
  formatSettingValue,
  settingChange,
  settingKind,
  settingProblem,
  settingTitle,
  settingUnit,
  WIDE_KINDS,
  type AdSetEdit,
  type SettingChange,
  type SettingEdit,
} from "@/integrations/meta_ads/lib/ad-set-edits"
import { BID_OPTIONS } from "@/integrations/meta_ads/lib/create-campaign"
import {
  CONVERSION_EVENT_LABELS,
  GOAL_KEYS,
  GOALS,
  STORE_OPTIONS,
  type Goal,
} from "@/integrations/meta_ads/lib/goals"
import { cn } from "@/lib/utils"

// One select holds both settings, so its values carry which one they set.
const EVENT = "event:"
const CUSTOM = "custom:"
const EVENT_OPTIONS = Object.entries(CONVERSION_EVENT_LABELS).map(([value, label]) => ({
  value: `${EVENT}${value}`,
  label,
}))

type FieldProps = {
  adSet: AdSetEdit
  disabled: boolean
  // Names of the Pages, pixels, apps, and custom conversions the card shows.
  labels: Record<string, string>
  onChange: (change: SettingChange) => void
  setting: SettingEdit
  strategy: string | null
}

/** One setting's new value, with its value now and any problem with the new one. */
export function AdSetEditField(props: FieldProps) {
  const { adSet, labels, setting } = props
  const currency = adSet.check?.currency ?? null
  const now = currentSetting(adSet, setting.key)
  const previous = now.value || null
  const percent = settingChange(setting, previous)
  const problem = settingProblem(setting)
  return (
    <div
      className={cn(
        "grid min-w-0 gap-1",
        WIDE_KINDS.has(settingKind(setting.key)) && "sm:col-span-2"
      )}
    >
      <SettingInput {...props} />
      <p className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
        Current Setting: {formatSettingValue(now.key, previous, currency, labels)}
        {percent ? (
          <Badge variant={Number(setting.value) < Number(previous) ? "secondary" : "success"}>
            {percent}
          </Badge>
        ) : null}
      </p>
      {problem ? <p className="text-destructive text-sm">{problem}</p> : null}
    </div>
  )
}

/** The create card's input for one new value; an optional one left empty clears the setting. */
function SettingInput({ adSet, disabled, labels, onChange, setting, strategy }: FieldProps) {
  const kind = settingKind(setting.key)
  const label = settingTitle(setting.key, strategy)
  const currency = adSet.check?.currency ?? null
  const invalid = settingProblem(setting) !== null
  const set = (value: EditedValue) => {
    onChange({ key: setting.key, value })
  }
  if (kind === "goal")
    return (
      <GoalField
        currentGoal={adSet.check?.before.goal ?? null}
        disabled={disabled}
        onChange={set}
        setting={setting}
      />
    )
  if (kind === "asset")
    return (
      <EntityPicker
        currentLabel={labels[setting.value] ?? setting.value}
        disabled={disabled}
        entityKind={ASSET_SETTINGS[setting.key]?.entityKind ?? setting.key}
        fieldKey="changes"
        label={label}
        onChoose={set}
        toolName="meta_ads_update_ad_sets"
      />
    )
  if (kind === "event" || kind === "custom")
    return (
      <ResultField
        conversions={adSet.check?.conversions ?? []}
        disabled={disabled}
        labels={labels}
        onChange={onChange}
        setting={setting}
      />
    )
  if (kind === "attribution")
    return <AttributionField disabled={disabled} onChange={set} value={setting.value} />
  if (kind === "frequency")
    return <FrequencyField disabled={disabled} onChange={set} value={setting.value} />
  if (kind === "schedule") {
    const current = adSet.check?.before.ad_schedule
    return (
      <AdScheduleField
        current={current ? parseAdSchedule(fromText(current)) : null}
        disabled={disabled}
        onChange={set}
        schedule={setting.value === "remove" ? null : parseAdSchedule(fromText(setting.value))}
      />
    )
  }
  if (kind === "bid" || kind === "store")
    return (
      <SelectField
        disabled={disabled}
        label={label}
        onChange={set}
        options={kind === "bid" ? BID_OPTIONS : STORE_OPTIONS}
        value={setting.value}
      />
    )
  if (kind === "money" || kind === "ratio")
    return (
      <MoneyField
        currency={kind === "ratio" ? null : currency}
        disabled={disabled}
        invalid={invalid}
        label={label}
        onChange={set}
        suffix={settingUnit(setting.key)}
        value={setting.value}
      />
    )
  if (kind === "limit")
    return (
      <MoneyField
        currency={currency}
        disabled={disabled}
        invalid={invalid}
        label={`${label} (Optional)`}
        onChange={(value) => {
          set(value || "remove")
        }}
        placeholder="No limit"
        suffix={settingUnit(setting.key)}
        value={setting.value === "remove" ? "" : setting.value}
      />
    )
  if (kind === "end")
    return (
      <TextField
        disabled={disabled}
        invalid={invalid}
        label={`${label} (Optional)`}
        onChange={(value) => {
          set(value || "none")
        }}
        type="date"
        value={setting.value === "none" ? "" : setting.value}
      />
    )
  return (
    <TextField
      disabled={disabled}
      invalid={invalid}
      label={label}
      onChange={set}
      type={kind === "date" ? "date" : "text"}
      value={setting.value}
    />
  )
}

/** Goals of the ad set's campaign objective, with what the chosen one optimises for. */
function GoalField({
  currentGoal,
  disabled,
  onChange,
  setting,
}: {
  currentGoal: string | null
  disabled: boolean
  onChange: (value: string) => void
  setting: SettingEdit
}) {
  const { value } = setting
  const objective =
    currentGoal && currentGoal in GOALS ? GOALS[currentGoal as Goal].objective : null
  const goals = GOAL_KEYS.filter((goal) => goal === value || GOALS[goal].objective === objective)
  return (
    <>
      <SelectField
        disabled={disabled}
        label="Goal"
        onChange={onChange}
        options={goals.map((goal) => ({ value: goal, label: GOALS[goal].label }))}
        value={value}
      />
      {value in GOALS ? (
        <p className="text-foreground/75 text-sm">{GOALS[value as Goal].description}</p>
      ) : null}
    </>
  )
}

/** Standard events and the account's custom conversions in one list, as Create Ad Set. */
function ResultField({
  conversions,
  disabled,
  labels,
  onChange,
  setting,
}: {
  conversions: readonly { id: string; name: string }[]
  disabled: boolean
  labels: Record<string, string>
  onChange: (change: SettingChange) => void
  setting: SettingEdit
}) {
  const custom = setting.key === "custom_conversion_id"
  const listed = conversions.some((item) => item.id === setting.value)
  const choices = [
    ...conversions,
    ...(custom && !listed
      ? [{ id: setting.value, name: labels[setting.value] ?? setting.value }]
      : []),
  ]
  return (
    <SelectField
      disabled={disabled}
      label="What Counts as a Result"
      onChange={(value) => {
        onChange(
          value.startsWith(CUSTOM)
            ? { key: "custom_conversion_id", value: value.slice(CUSTOM.length) }
            : { key: "conversion_event", value: value.slice(EVENT.length) }
        )
      }}
      options={[
        ...EVENT_OPTIONS,
        ...choices.map((item) => ({
          value: `${CUSTOM}${item.id}`,
          label: `Custom Conversion: ${item.name}`,
        })),
      ]}
      value={`${custom ? CUSTOM : EVENT}${setting.value}`}
    />
  )
}
