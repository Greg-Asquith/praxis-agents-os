// apps/web/src/components/tool-ui/message.tsx

import type { ReactElement, ReactNode } from "react"
import { MailIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export function MessageListRow({
  date,
  onSelect,
  provenance,
  renderSelect,
  sender,
  snippet,
  subject,
}: {
  date: string
  onSelect?: () => void
  provenance?: ReactNode
  renderSelect?: (control: ReactElement) => ReactNode
  sender: string
  snippet: string
  subject: string
}) {
  const content = (
    <div className="flex w-full min-w-0 items-start gap-2.5">
      <div className="bg-muted text-muted-foreground mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md">
        <MailIcon className="size-3.5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-baseline justify-between gap-3">
          <p className="min-w-0 flex-1 text-sm font-medium wrap-break-word">
            {sender || "Unknown sender"}
          </p>
          <time className="text-muted-foreground shrink-0 text-xs">{date}</time>
        </div>
        <p className="text-sm wrap-break-word">{subject || "(No subject)"}</p>
        <p className="text-muted-foreground mt-0.5 line-clamp-2 text-xs leading-relaxed wrap-break-word">
          {snippet || "No preview available."}
        </p>
        {provenance ? <div className="mt-1.5">{provenance}</div> : null}
      </div>
    </div>
  )

  return (
    <article className="hover:bg-muted/25 w-full min-w-0 rounded-md border px-3 py-2.5 transition-colors">
      {onSelect
        ? (renderSelect ?? identity)(
            <Button
              className="h-auto w-full min-w-0 justify-start p-0 text-left whitespace-normal"
              onClick={onSelect}
              type="button"
              variant="ghost"
            >
              {content}
            </Button>
          )
        : content}
    </article>
  )
}

function identity(control: ReactElement) {
  return control
}

export function MessageDetail({
  body,
  date,
  from,
  subject,
  to,
}: {
  body: ReactNode
  date: string
  from: string
  subject: string
  to: string
}) {
  return (
    <article className="min-w-0">
      <header className="border-border mb-3 border-b pb-3">
        <div className="min-w-0">
          <h3 className="text-sm font-medium wrap-break-word">{subject || "(No subject)"}</h3>
          <p className="text-muted-foreground mt-1 text-xs">{date}</p>
        </div>
        <dl className="mt-3 grid min-w-0 gap-2 text-xs sm:grid-cols-[3rem_1fr]">
          <dt className="text-muted-foreground">From</dt>
          <dd className="min-w-0 wrap-break-word">{from || "Unknown sender"}</dd>
          <dt className="text-muted-foreground">To</dt>
          <dd className="min-w-0 wrap-break-word">{to || "Unknown recipient"}</dd>
        </dl>
      </header>
      {body}
    </article>
  )
}

export function MessageDetailSkeleton({ label }: { label: string }) {
  return (
    <section aria-busy="true" aria-label={label} className={cn("grid min-w-0 gap-3 p-1")}>
      <div className="grid gap-2 border-b pb-3">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-2 h-3 w-1/2" />
      </div>
      <Skeleton className="h-28 w-full" />
      <span className="sr-only">{label}</span>
    </section>
  )
}
