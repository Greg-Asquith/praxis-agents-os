// apps/web/src/integrations/ads/components/cancel-cell.tsx

import { XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"

/** A change row's cell that takes the change out of the request, or puts it back. */
export function CancelCell({
  cancelled,
  disabled,
  onCancel,
  onUndo,
}: {
  cancelled: boolean
  disabled: boolean
  onCancel: () => void
  onUndo: () => void
}) {
  // A row that opens on click shouldn't open from these buttons.
  return cancelled ? (
    <Button
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation()
        onUndo()
      }}
      size="sm"
      type="button"
      variant="ghost"
    >
      Undo
    </Button>
  ) : (
    <Button
      aria-label="Cancel This Change"
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation()
        onCancel()
      }}
      size="icon-xs"
      title="Cancel This Change"
      type="button"
      variant="ghost"
    >
      <XIcon />
    </Button>
  )
}
