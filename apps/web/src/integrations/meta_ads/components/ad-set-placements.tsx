// apps/web/src/integrations/meta_ads/components/ad-set-placements.tsx

import { Checkbox } from "@/components/ui/checkbox"
import { ChoiceCards, SelectField } from "@/integrations/meta_ads/components/campaign-controls"
import {
  DEFAULT_POSITIONS,
  PLACEMENT_GROUPS,
  type Placements,
} from "@/integrations/meta_ads/lib/create-ad-set"

const MODE_OPTIONS = [
  { value: "automatic", label: "Everywhere Meta Chooses" },
  { value: "manual", label: "Only the Places I Choose" },
]
const DEVICE_OPTIONS = [
  { value: "all", label: "All Devices" },
  { value: "mobile", label: "Mobile Only" },
  { value: "desktop", label: "Desktop Only" },
]

/** Automatic placements, or checkboxes for the places and devices the ads may appear on. */
export function AdSetPlacements({
  disabled,
  onChange,
  placements,
}: {
  disabled: boolean
  onChange: (placements: Placements) => void
  placements: Placements
}) {
  const manual = placements.mode === "manual"
  const toggle = (position: string, on: boolean) => {
    const positions = on
      ? [...placements.positions, position]
      : placements.positions.filter((item) => item !== position)
    onChange({ ...placements, positions })
  }
  return (
    <>
      <ChoiceCards
        ariaLabel="Placements"
        columns={2}
        disabled={disabled}
        onChange={(mode) => {
          onChange(
            mode === "manual"
              ? { ...placements, mode: "manual", positions: DEFAULT_POSITIONS }
              : { ...placements, mode: "automatic", positions: [] }
          )
        }}
        options={MODE_OPTIONS}
        value={placements.mode}
      />
      {manual ? (
        <>
          {PLACEMENT_GROUPS.map((group) => (
            <fieldset className="grid min-w-0 gap-1" key={group.label}>
              <legend className="text-sm font-medium">{group.label}</legend>
              <div className="grid min-w-0 gap-x-4 sm:grid-cols-2">
                {group.positions.map(([position, label]) => (
                  <label className="flex min-h-8 items-center gap-2 text-sm" key={position}>
                    <Checkbox
                      checked={placements.positions.includes(position)}
                      disabled={disabled}
                      onCheckedChange={(on) => {
                        toggle(position, on)
                      }}
                    />
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
          <SelectField
            className="sm:max-w-64"
            disabled={disabled}
            label="Devices"
            onChange={(devices) => {
              onChange({ ...placements, devices })
            }}
            options={DEVICE_OPTIONS}
            value={placements.devices}
          />
          <p className="text-foreground/75 text-sm">
            Choosing places yourself stops the campaign qualifying as Advantage+.
          </p>
        </>
      ) : null}
    </>
  )
}
