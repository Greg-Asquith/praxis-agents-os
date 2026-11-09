// apps/web/src/integrations/ads/components/committed-input.tsx

import { Input } from "@/components/ui/input"

/** A table cell input that edits on leaving the field, so typing doesn't redraw the whole table. */
export function CommittedInput({
  ariaLabel,
  className,
  disabled,
  id,
  onCommit,
  placeholder,
  type,
  value,
}: {
  ariaLabel: string
  className?: string
  disabled: boolean
  id?: string
  onCommit: (value: string) => void
  placeholder?: string
  type?: string
  value: string
}) {
  return (
    <Input
      key={value}
      aria-label={ariaLabel}
      className={className ?? "h-7 text-sm"}
      defaultValue={value}
      disabled={disabled}
      id={id}
      onBlur={(event) => {
        if (event.currentTarget.value !== value) onCommit(event.currentTarget.value)
      }}
      onClick={(event) => {
        event.stopPropagation()
      }}
      onKeyDown={(event) => {
        // The row opens on Enter and Space, which also need to reach this field as text.
        event.stopPropagation()
      }}
      placeholder={placeholder}
      type={type}
    />
  )
}
