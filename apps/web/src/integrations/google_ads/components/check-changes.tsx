// apps/web/src/integrations/google_ads/components/check-changes.tsx

import { Button } from "@/components/ui/button"

/** Asks Google about an edited request; approval waits until the card has its answer. */
export function CheckChanges({
  canCheck,
  disabled,
  label = "Check Changes",
  note,
  onCheck,
  submitting,
}: {
  canCheck: boolean
  disabled: boolean
  label?: string
  note: string
  onCheck: (() => void) | undefined
  submitting: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <p className="text-muted-foreground text-sm" role="status">
        {submitting ? "Checking with Google…" : note}
      </p>
      <Button
        disabled={disabled || !canCheck || !onCheck}
        onClick={onCheck}
        type="button"
        variant="outline"
      >
        {label}
      </Button>
    </div>
  )
}
