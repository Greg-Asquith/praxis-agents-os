// apps/web/src/integrations/google_ads/components/text-asset-list.tsx

import { PlusIcon, XIcon } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { characterCount, type TextAsset } from "@/integrations/google_ads/lib/create-ads"
import { cn } from "@/lib/utils"

// Shown before Show All, so a 15-headline ad stays short.
const FIRST_SHOWN = 3
const NO_PIN = "none"

/** Edits an ad's headlines or descriptions, with character counters, pins, and the minimum. */
export function TextAssetList({
  assets,
  disabled,
  limits,
  noun,
  onChange,
  pins,
}: {
  assets: readonly TextAsset[]
  disabled: boolean
  limits: { min: number; max: number; length: number }
  noun: "Headline" | "Description"
  onChange: (assets: TextAsset[]) => void
  pins: readonly string[]
}) {
  const [showAll, setShowAll] = useState(false)
  const plural = `${noun}s`
  const shown = showAll ? assets : assets.slice(0, FIRST_SHOWN)
  const pinOptions = [
    { value: NO_PIN, label: "No Pin" },
    ...pins.map((pin, index) => ({ value: pin, label: `Pin to ${String(index + 1)}` })),
  ]
  const update = (index: number, patch: Partial<TextAsset>) => {
    onChange(assets.map((asset, at) => (at === index ? { ...asset, ...patch } : asset)))
  }
  const short = assets.length < limits.min
  return (
    <div className="grid min-w-0 gap-2">
      <p className="flex flex-wrap items-baseline gap-2 text-sm font-medium">
        {plural}
        <span
          className={cn(
            "text-xs font-normal",
            short ? "text-destructive" : "text-muted-foreground"
          )}
        >
          {String(assets.length)} of {String(limits.max)} · at least {String(limits.min)}
        </span>
      </p>
      <ul className="grid gap-1.5">
        {shown.map((asset, index) => {
          const count = characterCount(asset.text.trim())
          const over = count > limits.length || count === 0
          const label = `${noun} ${String(index + 1)}`
          return (
            // eslint-disable-next-line react-x/no-array-index-key -- Headlines have no ID, and a key from their text would remount the input, and lose focus, on each edit.
            <li key={index} className="flex min-w-0 items-center gap-2">
              <Input
                aria-invalid={over}
                aria-label={label}
                className="text-sm"
                disabled={disabled}
                onChange={(event) => {
                  update(index, { text: event.currentTarget.value })
                }}
                value={asset.text}
              />
              <span
                className={cn(
                  "w-12 shrink-0 text-right text-xs tabular-nums",
                  over ? "text-destructive font-medium" : "text-muted-foreground"
                )}
              >
                {String(count)}/{String(limits.length)}
              </span>
              <Select<string>
                disabled={disabled}
                onValueChange={(value) => {
                  update(index, { pin: value === null || value === NO_PIN ? null : value })
                }}
                value={asset.pin ?? NO_PIN}
              >
                <SelectTrigger
                  aria-label={`Pin ${label.toLowerCase()}`}
                  className="w-28 shrink-0"
                  size="sm"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end">
                  <SelectGroup>
                    {pinOptions.map((option) => (
                      <SelectItem key={option.value} label={option.label} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <Button
                aria-label={`Remove ${label.toLowerCase()}`}
                disabled={disabled}
                onClick={() => {
                  onChange(assets.filter((_, at) => at !== index))
                }}
                size="icon-xs"
                type="button"
                variant="ghost"
              >
                <XIcon />
              </Button>
            </li>
          )
        })}
      </ul>
      <div className="flex flex-wrap gap-2">
        {assets.length > FIRST_SHOWN ? (
          <Button
            onClick={() => {
              setShowAll(!showAll)
            }}
            size="sm"
            type="button"
            variant="link"
          >
            {showAll
              ? `Show First ${String(FIRST_SHOWN)}`
              : `Show All ${String(assets.length)} ${plural}`}
          </Button>
        ) : null}
        {assets.length < limits.max ? (
          <Button
            disabled={disabled}
            onClick={() => {
              setShowAll(true)
              onChange([...assets, { pin: null, text: "" }])
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            <PlusIcon />
            Add {noun}
          </Button>
        ) : null}
      </div>
    </div>
  )
}
