// apps/web/src/integrations/ads/components/status-choice.tsx

import { useId } from "react"

import { SegmentedChoice } from "@/integrations/ads/components/controls"

export type CreateStatus = "paused" | "active"

const LABELS: Record<CreateStatus, string> = { paused: "Paused", active: "Active" }

/** One line: whether a new object starts paused or active, and what that means. */
export function StatusChoice({
  activeNote,
  disabled,
  labels = LABELS,
  lockedNote = null,
  onChange,
  pausedNote,
  value,
}: {
  activeNote: string
  disabled: boolean
  // Each choice's button text, such as Build Paused and Launch.
  labels?: Record<CreateStatus, string>
  // Set when the status can't be changed, saying why.
  lockedNote?: string | null
  onChange: (value: CreateStatus) => void
  pausedNote: string
  value: CreateStatus
}) {
  const id = useId()
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
      <span className="font-medium" id={`${id}-label`}>
        Status
      </span>
      <SegmentedChoice
        ariaLabelledBy={`${id}-label`}
        compact
        disabled={disabled || lockedNote !== null}
        onChange={onChange}
        options={(["paused", "active"] as const).map((choice) => ({
          value: choice,
          label: labels[choice],
        }))}
        value={value}
      />
      <span className="text-muted-foreground min-w-0">
        {lockedNote ?? (value === "active" ? activeNote : pausedNote)}
      </span>
    </div>
  )
}
