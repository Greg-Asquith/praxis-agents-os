// apps/web/src/components/tool-ui/message.tsx

import { Fragment, useState, type ReactElement, type ReactNode } from "react"
import { MailIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyResult } from "@/components/tool-ui/empty-result"
import { pluralize } from "@/lib/format"
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
      {onSelect || renderSelect
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

// Opens the full message in a centred popover so long emails never stretch the result list.
export function MessagePreviewRow({
  children,
  date,
  onOpen,
  provenance,
  sender,
  snippet,
  subject,
}: {
  children: ReactNode
  date: string
  onOpen?: () => void
  provenance?: ReactNode
  sender: string
  snippet: string
  subject: string
}) {
  const [open, setOpen] = useState(false)

  return (
    <Popover
      onOpenChange={(next) => {
        setOpen(next)
        if (next) {
          onOpen?.()
        }
      }}
      open={open}
    >
      <MessageListRow
        date={date}
        provenance={provenance}
        renderSelect={(control) => <PopoverTrigger render={control} />}
        sender={sender}
        snippet={snippet}
        subject={subject}
      />
      {open ? (
        <PopoverContent
          centered
          className="max-h-[min(42rem,80vh)] w-[min(42rem,calc(100vw-2rem))] overflow-y-auto"
        >
          <PopoverHeader>
            <PopoverTitle>{subject || "(No subject)"}</PopoverTitle>
            <PopoverDescription>
              {sender || "Unknown sender"} · {date}
            </PopoverDescription>
          </PopoverHeader>
          {children}
        </PopoverContent>
      ) : null}
    </Popover>
  )
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

export function MessageList<T>({
  ariaLabel,
  emptyLabel,
  items,
  keyOf,
  renderItem,
}: {
  ariaLabel: string
  emptyLabel: string
  items: T[]
  keyOf: (item: T) => string
  renderItem: (item: T) => ReactNode
}) {
  if (items.length === 0) {
    return <EmptyResult>{emptyLabel}</EmptyResult>
  }
  return (
    <div className="grid min-w-0 gap-2">
      <p className="text-muted-foreground text-xs">
        {String(items.length)} {pluralize(items.length, "Message")}
      </p>
      <div
        aria-label={ariaLabel}
        className="grid max-h-[min(32rem,60vh)] min-w-0 gap-2 overflow-y-auto overscroll-contain pr-1"
        role="list"
      >
        {items.map((item) => (
          <div className="min-w-0" key={keyOf(item)} role="listitem">
            {renderItem(item)}
          </div>
        ))}
      </div>
    </div>
  )
}

// Compact header rows shared by outcome cards and draft reviews.
export function MessageHeaderRows({
  className,
  rows,
}: {
  className?: string
  rows: { label: string; value: string }[]
}) {
  return (
    <dl className={cn("grid min-w-0 gap-2 text-xs sm:grid-cols-[4rem_1fr]", className)}>
      {rows.map((row, index) => (
        <Fragment key={`${row.label}-${String(index)}`}>
          <dt className="text-muted-foreground">{row.label}</dt>
          <dd className="min-w-0 wrap-break-word">{row.value}</dd>
        </Fragment>
      ))}
    </dl>
  )
}
