// apps/web/src/integrations/meta_ads/components/editor-fields.tsx

import type { ReactNode } from "react"

import { fieldLabelClass, fieldWellClass } from "@/components/tool-ui/field-styles"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { CheckMessages } from "@/integrations/meta_ads/components/field-notes"
import { hasError, type AdCheck } from "@/integrations/meta_ads/lib/create-ads-checks"
import { cn } from "@/lib/utils"

const NO_CHECKS: readonly AdCheck[] = []

/** A label, its control, and the checks about it; narrow layouts put the counter below. */
export function EditorField({
  checks = NO_CHECKS,
  children,
  counter,
  counterBelow = false,
  id,
  label,
}: {
  checks?: readonly AdCheck[] | undefined
  children: ReactNode
  counter?: ReactNode
  counterBelow?: boolean | undefined
  id: string
  label: string
}) {
  return (
    <div className="grid min-w-0 gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <label className={fieldLabelClass} htmlFor={id}>
          {label}
        </label>
        {counterBelow ? null : counter}
      </div>
      {children}
      {counter && counterBelow ? <div className="flex justify-end">{counter}</div> : null}
      <CheckMessages checks={checks} />
    </div>
  )
}

export function LabelledInput({
  accessibleLabel,
  checks = NO_CHECKS,
  className,
  counter,
  counterBelow,
  disabled,
  id,
  inputMode,
  label,
  onChange,
  placeholder,
  value,
}: {
  accessibleLabel?: string | undefined
  checks?: readonly AdCheck[] | undefined
  className?: string | undefined
  counter?: ReactNode
  counterBelow?: boolean | undefined
  disabled: boolean
  id: string
  inputMode?: "url" | undefined
  label: string
  onChange: (value: string) => void
  placeholder?: string | undefined
  value: string
}) {
  return (
    <EditorField
      checks={checks}
      counter={counter}
      counterBelow={counterBelow}
      id={id}
      label={label}
    >
      <Input
        aria-invalid={hasError(checks)}
        aria-label={accessibleLabel}
        className={cn(fieldWellClass, "min-w-0", className)}
        disabled={disabled}
        id={id}
        inputMode={inputMode}
        onChange={(event) => {
          onChange(event.currentTarget.value)
        }}
        placeholder={placeholder}
        value={value}
      />
    </EditorField>
  )
}

export function LabelledSelect({
  accessibleLabel,
  checks = NO_CHECKS,
  disabled,
  id,
  label,
  note,
  onChange,
  options,
  value,
}: {
  accessibleLabel?: string | undefined
  checks?: readonly AdCheck[] | undefined
  disabled: boolean
  id: string
  label: string
  note?: string | null | undefined
  onChange: (value: string) => void
  options: readonly { value: string; label: string }[]
  value: string
}) {
  return (
    <EditorField checks={checks} id={id} label={label}>
      <Select<string>
        disabled={disabled}
        onValueChange={(next) => {
          if (next !== null) onChange(next)
        }}
        value={value}
      >
        <SelectTrigger
          aria-invalid={hasError(checks)}
          aria-label={accessibleLabel}
          className={cn(fieldWellClass, "h-8")}
          id={id}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="start">
          <SelectGroup>
            {options.map((option) => (
              <SelectItem key={option.value} label={option.label} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
      {note ? <p className="text-muted-foreground text-xs">{note}</p> : null}
    </EditorField>
  )
}
