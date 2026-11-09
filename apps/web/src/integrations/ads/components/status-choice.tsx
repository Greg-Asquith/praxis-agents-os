// apps/web/src/integrations/ads/components/status-choice.tsx

import { CirclePauseIcon, CirclePlayIcon } from "lucide-react"
import { useId } from "react"

import { SegmentedChoice } from "@/integrations/ads/components/controls"
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
        <SegmentedChoice
          ariaLabelledBy={`${id}-label`}
          disabled={disabled || lockedNote !== null}
          onChange={onChange}
          options={(["paused", "active"] as const).map((choice) => ({
            value: choice,
            label: labels[choice],
          }))}
          value={value}
        />
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
