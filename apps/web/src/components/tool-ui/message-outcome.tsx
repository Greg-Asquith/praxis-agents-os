// apps/web/src/components/tool-ui/message-outcome.tsx

import type { ReactNode } from "react"
import type { LucideIcon } from "lucide-react"

import { HtmlContentFrame } from "@/components/tool-ui/html-content-frame"
import { MessageHeaderRows } from "@/components/tool-ui/message"
import { cn } from "@/lib/utils"

export type MessageOutcome = "applied" | "failed" | "unverified"

export type MessageOutcomeView = {
  /** Approved HTML shown in the sandboxed frame; empty bodies render nothing. */
  body: string | null
  icons: Record<MessageOutcome, LucideIcon>
  linkLabel: (outcome: MessageOutcome) => string
  /** Muted line under the title once the change is confirmed. */
  note: string | null
  rows: { label: string; value: string }[]
  subject: string | null
  titles: Record<MessageOutcome, string>
}

const TONES: Record<MessageOutcome, { icon: string; title: string }> = {
  applied: { icon: "bg-success/10 text-success", title: "text-success" },
  failed: { icon: "bg-destructive/10 text-destructive", title: "text-destructive" },
  unverified: { icon: "bg-warning/15 text-warning-foreground", title: "text-warning-foreground" },
}

export function MessageWriteOutcome({
  description,
  outcome,
  recovery,
  url,
  view,
}: {
  description: string | null
  outcome: MessageOutcome
  /** Shown under the header rows when the provider returned no link to open. */
  recovery?: ReactNode
  url: string | null
  view: MessageOutcomeView
}) {
  const Icon = view.icons[outcome]
  const tone = TONES[outcome]
  const title = view.titles[outcome]
  const body = view.body?.trim() ? view.body : null
  const note = description ?? (outcome === "applied" ? view.note : null)
  const hasRows = view.rows.length > 0
  return (
    <article aria-label={title} className="min-w-0">
      <header
        className={cn(
          "flex min-w-0 items-start gap-3",
          (hasRows || body) && "border-border border-b pb-3"
        )}
      >
        <span
          className={cn("flex size-8 shrink-0 items-center justify-center rounded-full", tone.icon)}
        >
          <Icon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className={cn("text-xs font-medium", tone.title)}>{title}</p>
          {view.subject !== null ? (
            <h3 className="mt-0.5 text-sm font-medium wrap-break-word">
              {view.subject || "(No subject)"}
            </h3>
          ) : null}
          {note ? (
            <p className="text-muted-foreground mt-1 text-xs leading-relaxed">{note}</p>
          ) : null}
        </div>
        {url ? (
          <a
            className="text-link hover:text-primary shrink-0 text-xs font-medium underline underline-offset-2"
            href={url}
            rel="noreferrer"
            target="_blank"
          >
            {view.linkLabel(outcome)}
          </a>
        ) : null}
      </header>
      {hasRows ? (
        <MessageHeaderRows
          className={cn("py-3", body && "border-border border-b")}
          rows={view.rows}
        />
      ) : null}
      {url ? null : recovery}
      {body ? (
        <div className="pt-3">
          <HtmlContentFrame
            className="border-border h-80 rounded-lg border"
            html={body}
            title={view.subject ?? "Message"}
          />
        </div>
      ) : null}
    </article>
  )
}
