// apps/web/src/integrations/google_ads/components/bid-adjustment.tsx

import { useState } from "react"

import { Input } from "@/components/ui/input"
import { parseBidAdjustment } from "@/integrations/google_ads/lib/update-targeting"
import { cn } from "@/lib/utils"

function shown(value: number | null): string {
  if (value === null) return ""
  return value > 0 ? `+${String(value)}` : String(value)
}

/** A labelled bid adjustment as a percent, such as +15; blank means no adjustment. */
export function BidAdjustment({
  disabled,
  label,
  onChange,
  value,
}: {
  disabled: boolean
  label: string
  onChange: (value: number | null) => void
  value: number | null
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const text = draft ?? shown(value)
  const invalid = text.trim() !== "" && parseBidAdjustment(text) === null
  return (
    <label className="text-muted-foreground flex items-center gap-2 text-sm">
      Bid Adjustment
      <span className="relative inline-flex w-20 items-center">
        <Input
          aria-invalid={invalid}
          aria-label={label}
          className={cn(
            "text-right tabular-nums",
            text.trim() !== "" && "pr-6",
            invalid && "border-destructive"
          )}
          disabled={disabled}
          inputMode="numeric"
          onBlur={() => {
            setDraft(null)
            if (text.trim() === "") onChange(null)
            else if (!invalid) onChange(parseBidAdjustment(text))
          }}
          onChange={(event) => {
            setDraft(event.currentTarget.value)
          }}
          placeholder="None"
          value={text}
        />
        {text.trim() === "" ? null : (
          <span aria-hidden="true" className="text-muted-foreground absolute right-2 text-sm">
            %
          </span>
        )}
      </span>
    </label>
  )
}
