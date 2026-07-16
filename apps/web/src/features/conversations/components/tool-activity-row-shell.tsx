// apps/web/src/features/conversations/components/tool-activity-row-shell.tsx

import type { ReactNode } from "react"
import { ChevronRightIcon } from "lucide-react"

import { cn } from "@/lib/utils"

type ToolActivityRowHeaderProps = {
  expandable: boolean
  icon: ReactNode
  label: ReactNode
  reserveChevronSpace?: boolean
  suffix: ReactNode
  supportLabel: string | null
}

type ToolActivityRowShellProps = {
  children: ReactNode
  compact: boolean
  defaultOpen: boolean
  expandable: boolean
  header: ReactNode
}

export function ToolActivityRowHeader({
  expandable,
  icon,
  label,
  reserveChevronSpace = true,
  suffix,
  supportLabel,
}: ToolActivityRowHeaderProps) {
  const shouldRenderChevron = expandable || reserveChevronSpace

  return (
    <>
      {shouldRenderChevron ? (
        <ChevronRightIcon
          className={cn(
            "text-muted-foreground size-3.5 shrink-0 transition-transform group-open/tool:rotate-90",
            !expandable && "invisible"
          )}
        />
      ) : null}
      {icon}
      <span className="min-w-0 truncate">
        <span className="text-foreground font-medium">{label}</span>
        {supportLabel && (
          <span className="text-muted-foreground ml-1.5 font-mono text-xs">{supportLabel}</span>
        )}
      </span>
      {suffix}
    </>
  )
}

export function ToolActivityRowShell({
  children,
  compact,
  defaultOpen,
  expandable,
  header,
}: ToolActivityRowShellProps) {
  const textSize = compact ? "text-xs" : "text-sm"

  if (!expandable) {
    return (
      <div className={cn("text-muted-foreground flex min-w-0 items-center gap-2", textSize)}>
        {header}
      </div>
    )
  }

  return (
    <details className="group/tool min-w-0" open={defaultOpen ? true : undefined}>
      <summary
        className={cn(
          "text-muted-foreground hover:bg-muted/60 hover:text-foreground -mx-1.5 flex min-w-0 cursor-pointer list-none items-center gap-2 rounded-md px-1.5 py-1 transition-colors",
          textSize
        )}
      >
        {header}
      </summary>
      <div className="border-border/60 mt-1.5 ml-6 flex min-w-0 flex-col gap-3 border-l pl-3">
        {children}
      </div>
    </details>
  )
}
