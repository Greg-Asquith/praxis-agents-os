// apps/web/src/components/tool-ui/result-card.tsx

import { useState, type ReactNode } from "react"
import { ChevronRightIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"

const EMPTY_DETAILS: ToolResultDetail[] = []

export type ToolResultDetail = {
  label: string
  summary?: boolean
  value: string
}

export function ToolResultCard({
  ariaLabel,
  children,
  defaultOpen = false,
  details = EMPTY_DETAILS,
  expandable = true,
  heading,
  trailing,
}: {
  ariaLabel: string
  children?: ReactNode
  defaultOpen?: boolean
  details?: ToolResultDetail[]
  expandable?: boolean
  heading: ReactNode
  trailing?: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const summary = detailSummary(details)

  return (
    <section
      aria-label={ariaLabel}
      className="border-border/70 max-h-120 min-w-0 overflow-y-auto rounded-lg border"
    >
      <header
        className={cn(
          "bg-muted/25 flex min-w-0 items-center gap-2 rounded-lg p-1",
          expandable && open && "rounded-b-none border-b"
        )}
      >
        {expandable ? (
          <Button
            aria-expanded={open}
            aria-label={open ? "Collapse results" : "Expand results"}
            className="h-auto min-w-0 flex-1 justify-start px-1.5 py-0.5 text-left whitespace-normal"
            onClick={() => {
              setOpen((current) => !current)
            }}
            type="button"
            variant="ghost"
          >
            <ChevronRightIcon className={cn("transition-transform", open && "rotate-90")} />
            <span className="min-w-0 flex-1">
              <span className="block min-w-0 text-sm font-medium">{heading}</span>
              <span className="text-muted-foreground block truncate text-xs" title={summary}>
                {summary}
              </span>
            </span>
          </Button>
        ) : (
          <div className="min-w-0 flex-1 px-1.5 py-0.5 text-sm font-medium">{heading}</div>
        )}
        {expandable ? <ToolResultDetailsPopover details={details} /> : null}
        {trailing}
      </header>
      {expandable && open ? <div className="min-w-0 p-3">{children}</div> : null}
    </section>
  )
}

function ToolResultDetailsPopover({ details }: { details: ToolResultDetail[] }) {
  return (
    <Popover>
      <PopoverTrigger render={<Button size="xs" type="button" variant="ghost" />}>
        Details
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="max-h-[min(28rem,70vh)] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto"
      >
        <PopoverHeader>
          <PopoverTitle>Details</PopoverTitle>
        </PopoverHeader>
        <dl className="grid min-w-0 gap-2 text-xs">
          {details.map((detail) => (
            <div className="grid min-w-0 gap-0.5" key={`${detail.label}:${detail.value}`}>
              <dt className="text-muted-foreground">{detail.label}</dt>
              <dd className="min-w-0 wrap-break-word whitespace-pre-wrap">{detail.value}</dd>
            </div>
          ))}
        </dl>
      </PopoverContent>
    </Popover>
  )
}

function detailSummary(details: ToolResultDetail[]): string {
  return details
    .filter((detail) => detail.summary !== false)
    .map((detail) => `${detail.label}: ${detail.value}`)
    .join(" · ")
}
