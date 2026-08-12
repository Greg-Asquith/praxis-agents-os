import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react"

import { Button } from "@/components/ui/button"

type PaginationControlsProps = {
  ariaLabel?: string
  disabled?: boolean
  limit: number
  offset: number
  onPageChange: (offset: number) => void
  total: number
}

export function paginateItems<T>(items: T[], requestedOffset: number, limit: number) {
  const maximumOffset = Math.max(0, Math.floor(Math.max(0, items.length - 1) / limit) * limit)
  const offset = Math.min(Math.max(0, requestedOffset), maximumOffset)
  return { items: items.slice(offset, offset + limit), offset }
}

export function PaginationControls({
  ariaLabel = "Pagination",
  disabled = false,
  limit,
  offset,
  onPageChange,
  total,
}: PaginationControlsProps) {
  const start = total === 0 ? 0 : offset + 1
  const end = Math.min(offset + limit, total)
  const hasPrevious = offset > 0
  const hasNext = offset + limit < total

  return (
    <nav
      aria-label={ariaLabel}
      className="flex flex-col gap-3 border-t pt-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <p aria-live="polite" className="text-muted-foreground text-sm" role="status">
        Showing {start}-{end} of {total}
      </p>
      <div className="flex items-center gap-2">
        <Button
          disabled={disabled || !hasPrevious}
          onClick={() => {
            onPageChange(Math.max(0, offset - limit))
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          <ChevronLeftIcon data-icon="inline-start" />
          Previous
        </Button>
        <Button
          disabled={disabled || !hasNext}
          onClick={() => {
            onPageChange(offset + limit)
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          Next
          <ChevronRightIcon data-icon="inline-end" />
        </Button>
      </div>
    </nav>
  )
}
