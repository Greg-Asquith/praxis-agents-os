// apps/web/src/components/tool-ui/scalar-field-input.tsx

import type { ApprovalField } from "@/components/tool-ui/approval-types"
import type { EditedScalar } from "@/components/tool-ui/edited-values"
import { fieldWellClass } from "@/components/tool-ui/field-styles"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"

type ScalarFieldInputProps = {
  disabled: boolean
  id: string
  onChange: (value: EditedScalar) => void
  onClear: () => void
  focusRef: (node: HTMLElement | null) => void
  rawValue: unknown
  value: unknown
}

export function ScalarFieldInput(
  props: ScalarFieldInputProps & { format: ApprovalField["format"] }
) {
  const { disabled, format, id, onChange, onClear, focusRef, value } = props
  if (format === "number" && typeof value === "number") {
    return <NumberFieldInput {...props} value={value} />
  }
  if (format === "boolean" && typeof value === "boolean") {
    return (
      <Checkbox
        checked={value}
        disabled={disabled}
        id={id}
        onCheckedChange={onChange}
        ref={focusRef}
      />
    )
  }
  if (format === "datetime" && typeof value === "string") {
    return (
      <Input
        className={fieldWellClass}
        disabled={disabled}
        id={id}
        onChange={(event) => {
          const nextValue = event.currentTarget.value
          if (nextValue) {
            onChange(nextValue)
          } else {
            onClear()
          }
        }}
        ref={focusRef}
        step={60}
        type="datetime-local"
        value={value}
      />
    )
  }
  return null
}

function NumberFieldInput({
  disabled,
  id,
  onChange,
  onClear,
  focusRef,
  rawValue,
  value,
}: ScalarFieldInputProps & { value: number }) {
  return (
    <Input
      className={fieldWellClass}
      defaultValue={value}
      disabled={disabled}
      id={id}
      inputMode="decimal"
      onChange={(event) => {
        const raw = event.currentTarget.value
        const nextValue = Number(raw)
        if (!raw) {
          onClear()
        } else if (
          Number.isFinite(nextValue) &&
          (!Number.isInteger(rawValue) || Number.isInteger(nextValue))
        ) {
          onChange(nextValue)
        } else {
          event.currentTarget.value = String(value)
        }
      }}
      ref={focusRef}
      step={Number.isInteger(rawValue) ? 1 : "any"}
      type="number"
    />
  )
}
