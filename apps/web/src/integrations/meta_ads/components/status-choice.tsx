// apps/web/src/integrations/meta_ads/components/status-choice.tsx

import { CirclePauseIcon, CirclePlayIcon } from "lucide-react"
import { useId } from "react"

import { cn } from "@/lib/utils"

export type CreateStatus = "paused" | "active"

const LABELS: Record<CreateStatus, string> = { paused: "Paused", active: "Active" }

/** Whether a new object starts paused or active, with what that means for spend. */
export function StatusChoice({
  activeNote,
  disabled,
  label,
  labels = LABELS,
  lockedNote = null,
  onChange,
  pausedNote,
  value,
}: {
  activeNote: string
  disabled: boolean
  label: string
  // Each choice's button text, such as Build Paused and Launch.
  labels?: Record<CreateStatus, string>
  // Set when the status can't be changed, saying why.
  lockedNote?: string | null
  onChange: (value: CreateStatus) => void
  pausedNote: string
  value: CreateStatus
}) {
  const id = useId()
  const active = value === "active"
  const Icon = active ? CirclePlayIcon : CirclePauseIcon
  return (
    <div
      className={cn(
        "grid min-w-0 gap-2 rounded-lg border px-3 py-2.5",
        active ? "border-warning/40 bg-warning/10" : "bg-muted/40 border-transparent"
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-sm font-medium" id={`${id}-label`}>
          {label}
        </span>
        <div
          aria-labelledby={`${id}-label`}
          className="bg-background flex rounded-lg border p-0.5"
          role="radiogroup"
        >
          {(["paused", "active"] as const).map((choice) => {
            const checked = choice === value
            return (
              <button
                key={choice}
                aria-checked={checked}
                className={cn(
                  "focus-visible:ring-ring/50 h-8 min-w-20 cursor-pointer rounded-md px-3 text-sm font-medium outline-none focus-visible:ring-3 disabled:cursor-not-allowed disabled:opacity-60",
                  checked && choice === "paused" && "bg-foreground text-background",
                  checked && choice === "active" && "bg-primary text-primary-foreground",
                  !checked && "text-foreground/70 hover:bg-muted"
                )}
                disabled={disabled || lockedNote !== null}
                onClick={() => {
                  if (!checked) onChange(choice)
                }}
                role="radio"
                type="button"
              >
                {labels[choice]}
              </button>
            )
          })}
        </div>
      </div>
      <p
        className={cn(
          "flex items-start gap-2 text-sm",
          active ? "text-warning-text font-medium" : "text-foreground/75"
        )}
      >
        <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span>{lockedNote ?? (active ? activeNote : pausedNote)}</span>
      </p>
    </div>
  )
}
