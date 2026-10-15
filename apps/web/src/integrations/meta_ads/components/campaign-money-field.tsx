// apps/web/src/integrations/meta_ads/components/campaign-money-field.tsx

import { useId } from "react"

import { Input } from "@/components/ui/input"
import { currencySymbol } from "@/lib/format"
import { cn } from "@/lib/utils"

/** A labelled amount in the ad account currency, with an optional unit such as "a day". */
export function MoneyField({
  className,
  currency,
  disabled,
  invalid = false,
  label,
  onChange,
  placeholder,
  suffix,
  value,
}: {
  className?: string | undefined
  currency: string | null
  disabled: boolean
  invalid?: boolean
  label: string
  onChange: (value: string) => void
  placeholder?: string | undefined
  suffix?: string | undefined
  value: string
}) {
  const id = useId()
  const symbol = currency ? currencySymbol(currency) : null
  return (
    <div className={cn("grid min-w-0 gap-1", className)}>
      <label className="text-sm font-medium" htmlFor={id}>
        {label}
      </label>
      <div className="relative flex min-w-0 items-center">
        {symbol ? (
          <span
            aria-hidden="true"
            className="text-muted-foreground pointer-events-none absolute left-2.5 text-sm"
          >
            {symbol}
          </span>
        ) : null}
        <Input
          aria-invalid={invalid}
          className={cn("text-sm tabular-nums", symbol && "pl-7", suffix && "pr-16")}
          disabled={disabled}
          id={id}
          inputMode="decimal"
          onChange={(event) => {
            onChange(event.currentTarget.value.trim())
          }}
          placeholder={placeholder}
          value={value}
        />
        {suffix ? (
          <span
            aria-hidden="true"
            className="text-muted-foreground pointer-events-none absolute right-2.5 text-sm"
          >
            {suffix}
          </span>
        ) : null}
      </div>
    </div>
  )
}
