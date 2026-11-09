// apps/web/src/integrations/ads/components/controls.tsx

import { XIcon } from "lucide-react"
import { useId, type ReactNode } from "react"

import { Input } from "@/components/ui/input"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

type Option = { value: string; label: string; description?: string; disabledNote?: string }

/** Radio cards for a short list of choices, each with an optional plain explanation. */
export function ChoiceCards({
  ariaLabel,
  columns = 1,
  disabled,
  onChange,
  options,
  value,
}: {
  ariaLabel: string
  columns?: 1 | 2 | 3
  disabled: boolean
  onChange: (value: string) => void
  options: readonly Option[]
  value: string
}) {
  return (
    <RadioGroup
      aria-label={ariaLabel}
      className={cn(
        "min-w-0 gap-2",
        columns === 2 && "sm:grid-cols-2",
        columns === 3 && "sm:grid-cols-3"
      )}
      disabled={disabled}
      onValueChange={(next) => {
        if (typeof next === "string" && next !== value) onChange(next)
      }}
      value={value}
    >
      {options.map((option) => (
        <label
          key={option.value}
          className={cn(
            "bg-background hover:bg-muted/60 has-data-checked:border-primary has-data-checked:bg-accent/60 flex min-h-10 min-w-0 cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 text-sm transition-colors",
            (disabled || option.disabledNote !== undefined) &&
              "hover:bg-background cursor-not-allowed opacity-60"
          )}
        >
          <RadioGroupItem
            className="mt-0.5"
            disabled={disabled || option.disabledNote !== undefined}
            value={option.value}
          />
          <span className="grid min-w-0 gap-0.5">
            <span className="font-medium">{option.label}</span>
            {option.description || option.disabledNote ? (
              <span className="text-foreground/75">
                {option.disabledNote ?? option.description}
              </span>
            ) : null}
          </span>
        </label>
      ))}
    </RadioGroup>
  )
}

/** A short either-or choice as one segmented control, such as Paused or Active. */
export function SegmentedChoice<T extends string>({
  ariaLabel,
  ariaLabelledBy,
  className,
  disabled,
  onChange,
  options,
  value,
}: {
  ariaLabel?: string
  ariaLabelledBy?: string
  className?: string
  disabled: boolean
  onChange: (value: T) => void
  options: readonly { value: T; label: string }[]
  value: T | null
}) {
  return (
    <ToggleGroup
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      className={cn("bg-background rounded-lg border p-0.5", className)}
      disabled={disabled}
      onValueChange={(next) => {
        // Pressing the chosen item again would clear it, so only a new choice counts.
        const chosen = options.find(
          (option) => next.includes(option.value) && option.value !== value
        )
        if (chosen) onChange(chosen.value)
      }}
      spacing={0.5}
      value={value === null ? [] : [value]}
    >
      {options.map((option) => (
        <ToggleGroupItem
          key={option.value}
          className="text-foreground/70 aria-pressed:bg-accent aria-pressed:text-accent-foreground h-8 min-w-20 px-3 aria-pressed:font-semibold"
          value={option.value}
        >
          {option.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}

/** A text-sm label above one control; the control receives the id the label points at. */
export function FormField({
  children,
  className,
  label,
}: {
  children: (id: string) => ReactNode
  className?: string | undefined
  label: string
}) {
  const id = useId()
  return (
    <div className={cn("grid min-w-0 gap-1", className)}>
      <label className="text-sm font-medium" htmlFor={id}>
        {label}
      </label>
      {children(id)}
    </div>
  )
}

export function TextField({
  disabled,
  inputMode,
  invalid = false,
  label,
  onChange,
  placeholder,
  type = "text",
  value,
}: {
  disabled: boolean
  inputMode?: "numeric" | "decimal"
  invalid?: boolean
  label: string
  onChange: (value: string) => void
  placeholder?: string
  type?: "text" | "date" | "datetime-local"
  value: string
}) {
  return (
    <FormField label={label}>
      {(id) => (
        <Input
          aria-invalid={invalid}
          className="text-sm"
          disabled={disabled}
          id={id}
          inputMode={inputMode}
          onChange={(event) => {
            onChange(event.currentTarget.value)
          }}
          placeholder={placeholder}
          type={type}
          value={value}
        />
      )}
    </FormField>
  )
}

export function SelectField({
  className,
  disabled,
  label,
  onChange,
  options,
  placeholder,
  value,
}: {
  className?: string | undefined
  disabled: boolean
  label: string
  onChange: (value: string) => void
  options: readonly { value: string; label: string }[]
  placeholder?: string
  value: string | null
}) {
  return (
    <FormField className={className} label={label}>
      {(id) => (
        <Select<string>
          disabled={disabled}
          onValueChange={(next) => {
            if (next !== null) onChange(next)
          }}
          value={value}
        >
          <SelectTrigger className="w-full" id={id}>
            <SelectValue placeholder={placeholder} />
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
      )}
    </FormField>
  )
}

export function SwitchField({
  checked,
  description,
  disabled,
  label,
  onChange,
}: {
  checked: boolean
  description?: string
  disabled: boolean
  label: string
  onChange: (checked: boolean) => void
}) {
  const id = useId()
  return (
    <div className="flex min-w-0 items-start gap-3 text-sm">
      <Switch
        checked={checked}
        className="mt-0.5"
        disabled={disabled}
        id={id}
        onCheckedChange={onChange}
      />
      <label className="grid min-w-0 gap-0.5" htmlFor={id}>
        <span className="font-medium">{label}</span>
        {description ? <span className="text-foreground/75">{description}</span> : null}
      </label>
    </div>
  )
}

/** A chosen item with a remove button, such as a country or an interest. */
export function Chip({
  detail,
  disabled,
  label,
  onRemove,
}: {
  detail?: string | null | undefined
  disabled: boolean
  label: string
  onRemove: () => void
}) {
  return (
    <span className="bg-background inline-flex h-8 max-w-full min-w-0 items-center rounded-full border pl-3 text-sm">
      <span className="truncate">{label}</span>
      {detail ? <span className="text-muted-foreground ml-1.5 shrink-0">{detail}</span> : null}
      <button
        aria-label={`Remove ${label}`}
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 ml-1 flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full outline-none focus-visible:ring-3 disabled:cursor-not-allowed disabled:opacity-50"
        disabled={disabled}
        onClick={onRemove}
        type="button"
      >
        <XIcon aria-hidden="true" className="size-4" />
      </button>
    </span>
  )
}
