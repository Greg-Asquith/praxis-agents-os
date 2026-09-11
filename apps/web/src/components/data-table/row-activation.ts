// apps/web/src/components/data-table/row-activation.ts

import type { KeyboardEvent } from "react"

export const ACTIVATABLE_ROW_CLASS_NAME =
  "hover:bg-muted/50 focus-visible:ring-ring cursor-pointer focus-visible:ring-2 focus-visible:outline-none"

// Rows open on Enter or Space only when the row itself has focus, so nested controls keep theirs.
export function handleRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, open: () => void) {
  if (event.target !== event.currentTarget) {
    return
  }
  if (event.key !== "Enter" && event.key !== " ") {
    return
  }
  event.preventDefault()
  open()
}

export function stopRowClick(event: { stopPropagation: () => void }) {
  event.stopPropagation()
}
