// apps/web/src/integrations/meta_ads/components/setting-rows.tsx

import { ChevronDownIcon } from "lucide-react"
import { createContext, use, useId, useMemo, useState, type ReactNode } from "react"

import { cn } from "@/lib/utils"

type OpenRow = { open: string | null; setOpen: (key: string | null) => void }

const OpenRowContext = createContext<OpenRow | null>(null)

/** Settings as one-line rows; opening a row closes the one that was open, to save height. */
export function SettingRows({
  ariaLabel,
  bare = false,
  children,
  defaultOpen = null,
}: {
  ariaLabel: string
  // True inside a row of another SettingRows, which already draws the border.
  bare?: boolean
  children: ReactNode
  defaultOpen?: string | null
}) {
  const [open, setOpen] = useState(defaultOpen)
  const value = useMemo(() => ({ open, setOpen }), [open])
  return (
    <OpenRowContext value={value}>
      <section
        aria-label={ariaLabel}
        className={cn("divide-y", !bare && "overflow-hidden rounded-lg border")}
      >
        {children}
      </section>
    </OpenRowContext>
  )
}

/** One setting: its title and current value on one line, its controls when opened. */
export function SettingRow({
  children,
  rowKey,
  summary,
  title,
  tone = "neutral",
}: {
  children: ReactNode
  rowKey: string
  summary: ReactNode
  title: string
  tone?: "neutral" | "warning" | "error"
}) {
  const id = useId()
  const rows = use(OpenRowContext)
  const [ownOpen, setOwnOpen] = useState(false)
  const open = rows ? rows.open === rowKey : ownOpen
  const toggle = () => {
    if (rows) rows.setOpen(open ? null : rowKey)
    else setOwnOpen(!open)
  }
  return (
    <div className={cn("min-w-0", open && "bg-muted/40")}>
      <button
        aria-controls={open ? `${id}-body` : undefined}
        aria-expanded={open}
        className="hover:bg-muted/60 focus-visible:ring-ring/50 flex min-h-11 w-full min-w-0 cursor-pointer items-center gap-3 px-3 py-2 text-left outline-none focus-visible:ring-3 focus-visible:ring-inset"
        onClick={toggle}
        type="button"
      >
        <span className="w-36 shrink-0 text-sm font-medium">{title}</span>
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-sm",
            tone === "warning" && "text-warning-text",
            tone === "error" && "text-destructive",
            tone === "neutral" && "text-foreground/80"
          )}
        >
          {summary}
        </span>
        <ChevronDownIcon
          aria-hidden="true"
          className={cn(
            "text-muted-foreground size-4 shrink-0 transition-transform",
            open && "rotate-180"
          )}
        />
      </button>
      {open ? (
        <div className="grid min-w-0 gap-3 px-3 pt-1 pb-3" id={`${id}-body`}>
          {children}
        </div>
      ) : null}
    </div>
  )
}

/** A setting that is always shown, such as the name, laid out like a closed row. */
export function SettingLine({
  children,
  htmlFor,
  title,
}: {
  children: ReactNode
  htmlFor?: string | undefined
  title: string
}) {
  return (
    <div className="flex min-h-11 min-w-0 items-center gap-3 px-3 py-1.5">
      <label className="w-36 shrink-0 text-sm font-medium" htmlFor={htmlFor}>
        {title}
      </label>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}
