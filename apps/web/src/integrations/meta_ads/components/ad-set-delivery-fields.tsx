// apps/web/src/integrations/meta_ads/components/ad-set-delivery-fields.tsx

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { ChoiceCards, SelectField } from "@/integrations/meta_ads/components/campaign-controls"
import {
  fromText,
  parseAttribution,
  parseFrequencyCap,
} from "@/integrations/meta_ads/lib/ad-set-delivery"

const CLICK_OPTIONS = [
  { value: "1", label: "1 Day" },
  { value: "7", label: "7 Days" },
]
const VIEW_OPTIONS = [
  { value: "0", label: "None" },
  { value: "1", label: "1 Day" },
]
const CAP_MODES = [
  {
    value: "none",
    label: "No Cap",
    description: "Meta decides how often each person sees the ads.",
  },
  { value: "cap", label: "Set a Cap", description: "Limit how often one person sees them." },
]
const TIMES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
const DAYS = [1, 7, 14, 30, 60, 90]

/** The days after a click, view, or engaged video view in which a result counts. */
export function AttributionField({
  disabled,
  onChange,
  value,
}: {
  disabled: boolean
  onChange: (value: EditedValue) => void
  value: string
}) {
  const attribution = parseAttribution(fromText(value)) ?? {
    click_days: 7,
    view_days: 1,
    engaged_view_days: 0,
  }
  const set = (key: keyof typeof attribution) => (days: string) => {
    onChange({ ...attribution, [key]: Number(days) })
  }
  return (
    <div className="grid min-w-0 gap-2">
      <p className="text-foreground/75 text-sm">
        Results count when someone acts within these days of clicking or seeing an ad.
      </p>
      <div className="grid min-w-0 gap-2 sm:grid-cols-3">
        <SelectField
          disabled={disabled}
          label="After a Click"
          onChange={set("click_days")}
          options={CLICK_OPTIONS}
          value={String(attribution.click_days)}
        />
        <SelectField
          disabled={disabled}
          label="After a View"
          onChange={set("view_days")}
          options={VIEW_OPTIONS}
          value={String(attribution.view_days)}
        />
        <SelectField
          disabled={disabled}
          label="After an Engaged Video View"
          onChange={set("engaged_view_days")}
          options={VIEW_OPTIONS}
          value={String(attribution.engaged_view_days)}
        />
      </div>
    </div>
  )
}

// A proposed value outside the usual steps stays on the list, so the select shows it.
function steps(values: readonly number[], current: number): number[] {
  return [...new Set([...values, current])].sort((a, b) => a - b)
}

/** A cap on how often one person sees the ads; No Cap sends "remove". */
export function FrequencyField({
  disabled,
  onChange,
  value,
}: {
  disabled: boolean
  onChange: (value: EditedValue) => void
  value: string
}) {
  const capped = value !== "remove"
  const cap = parseFrequencyCap(capped ? fromText(value) : null) ?? {
    max_impressions: 2,
    every_days: 7,
  }
  const set = (key: keyof typeof cap) => (next: string) => {
    onChange({ ...cap, [key]: Number(next) })
  }
  return (
    <div className="grid min-w-0 gap-3">
      <ChoiceCards
        ariaLabel="Frequency Cap"
        columns={2}
        disabled={disabled}
        onChange={(mode) => {
          onChange(mode === "cap" ? cap : "remove")
        }}
        options={CAP_MODES}
        value={capped ? "cap" : "none"}
      />
      {capped ? (
        <div className="grid gap-2 sm:grid-cols-2">
          <SelectField
            disabled={disabled}
            label="Each Person Sees the Ads"
            onChange={set("max_impressions")}
            options={steps(TIMES, cap.max_impressions).map((times) => ({
              value: String(times),
              label: times === 1 ? "At most once" : `At most ${String(times)} times`,
            }))}
            value={String(cap.max_impressions)}
          />
          <SelectField
            disabled={disabled}
            label="In"
            onChange={set("every_days")}
            options={steps(DAYS, cap.every_days).map((days) => ({
              value: String(days),
              label: days === 1 ? "1 day" : `${String(days)} days`,
            }))}
            value={String(cap.every_days)}
          />
        </div>
      ) : null}
    </div>
  )
}
