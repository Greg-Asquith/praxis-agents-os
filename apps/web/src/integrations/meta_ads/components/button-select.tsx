// apps/web/src/integrations/meta_ads/components/button-select.tsx

import { fieldOptionLabel } from "@/components/tool-ui/field-options"
import { LabelledSelect } from "@/integrations/meta_ads/components/editor-fields"
import type { AdCheck } from "@/integrations/meta_ads/lib/create-ads-checks"

const INHERIT = "inherit"

/** Picks a button; with `fallbackLabel`, it can also leave the choice to that value. */
export function ButtonSelect({
  allowed,
  checks,
  disabled,
  fallbackLabel,
  id,
  label,
  onChange,
  value,
}: {
  allowed: readonly string[]
  checks?: readonly AdCheck[] | undefined
  disabled: boolean
  fallbackLabel?: string | undefined
  id: string
  label: string
  onChange: (value: string | null) => void
  value: string | null
}) {
  // A button the goal doesn't allow stays visible, so the error next to it makes sense.
  const buttons = value && !allowed.includes(value) ? [value, ...allowed] : allowed
  const options = buttons.map((button) => ({ value: button, label: fieldOptionLabel(button) }))
  return (
    <LabelledSelect
      accessibleLabel={label}
      checks={checks}
      disabled={disabled}
      id={id}
      label="CTA Button"
      onChange={(next) => {
        onChange(next === INHERIT ? null : next)
      }}
      options={fallbackLabel ? [{ value: INHERIT, label: fallbackLabel }, ...options] : options}
      value={value ?? INHERIT}
    />
  )
}
