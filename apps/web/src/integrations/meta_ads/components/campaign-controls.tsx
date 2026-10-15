// apps/web/src/integrations/meta_ads/components/campaign-controls.tsx

import { XIcon } from "lucide-react"
import { useId, type ReactNode } from "react"

import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
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
    <div
      aria-label={ariaLabel}
      className={cn(
        "grid min-w-0 gap-2",
        columns === 2 && "sm:grid-cols-2",
        columns === 3 && "sm:grid-cols-3"
      )}
      role="radiogroup"
    >
      {options.map((option) => {
        const checked = option.value === value
        return (
          <button
            key={option.value}
            aria-checked={checked}
            className={cn(
              "focus-visible:ring-ring/50 flex min-h-10 min-w-0 cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-left text-sm outline-none focus-visible:ring-3 disabled:cursor-not-allowed disabled:opacity-60",
              checked ? "border-primary bg-primary/5" : "bg-background hover:bg-muted/60"
            )}
            disabled={disabled || option.disabledNote !== undefined}
            onClick={() => {
              if (!checked) onChange(option.value)
            }}
            role="radio"
            type="button"
          >
            <span
              aria-hidden="true"
              className={cn(
                "mt-0.5 size-4 shrink-0 rounded-full border",
                checked ? "border-primary border-[5px]" : "border-muted-foreground/60"
              )}
            />
            <span className="grid min-w-0 gap-0.5">
              <span className="font-medium">{option.label}</span>
              {option.description || option.disabledNote ? (
                <span className="text-foreground/75">
                  {option.disabledNote ?? option.description}
                </span>
              ) : null}
            </span>
          </button>
        )
      })}
    </div>
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
  type?: "text" | "date"
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
