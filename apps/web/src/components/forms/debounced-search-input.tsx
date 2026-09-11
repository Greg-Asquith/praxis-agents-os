// apps/web/src/components/forms/debounced-search-input.tsx

import { useEffect, useState } from "react"
import { SearchIcon } from "lucide-react"

import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

const DEFAULT_DELAY_MS = 300

// Committed search text lives in the URL; the draft stays local until the debounce settles.
export function DebouncedSearchInput({
  ariaLabel,
  className,
  delayMs = DEFAULT_DELAY_MS,
  disabled = false,
  onChange,
  placeholder,
  value,
}: {
  ariaLabel: string
  className?: string
  delayMs?: number
  disabled?: boolean
  onChange: (value: string) => void
  placeholder: string
  value: string
}) {
  const [draft, setDraft] = useState(value)
  const [syncedValue, setSyncedValue] = useState(value)
  if (value !== syncedValue) {
    setSyncedValue(value)
    setDraft(value)
  }

  useEffect(() => {
    const trimmed = draft.trim()
    if (trimmed === value) return
    const timer = window.setTimeout(() => {
      onChange(trimmed)
    }, delayMs)
    return () => {
      window.clearTimeout(timer)
    }
  }, [delayMs, draft, onChange, value])

  return (
    <div className={cn("relative w-full sm:w-72", className)}>
      <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
      <Input
        aria-label={ariaLabel}
        className="pl-8"
        disabled={disabled}
        onChange={(event) => {
          setDraft(event.target.value)
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            onChange(draft.trim())
          } else if (event.key === "Escape" && draft) {
            setDraft("")
            onChange("")
          }
        }}
        placeholder={placeholder}
        type="search"
        value={draft}
      />
    </div>
  )
}
