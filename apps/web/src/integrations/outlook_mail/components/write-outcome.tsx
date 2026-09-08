// apps/web/src/integrations/outlook_mail/components/write-outcome.tsx

import { Fragment } from "react"
import type { LucideIcon } from "lucide-react"

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { OutlookMessageRecovery } from "@/integrations/outlook_mail/components/message-recovery"
import type { OutlookMessageReference } from "@/integrations/outlook_mail/lib/write-args"
import { HtmlContentFrame } from "@/components/tool-ui/html-content-frame"
import type { OutlookOutcome } from "@/integrations/outlook_mail/lib/write-results"
import { cn } from "@/lib/utils"

export type OutlookOutcomeView = {
  /** Approved HTML shown in the sandboxed frame; empty bodies render nothing. */
  body: string | null
  icons: Record<OutlookOutcome, LucideIcon>
  linkLabel: (outcome: OutlookOutcome) => string
  /** Muted line under the title once the change is confirmed. */
  note: string | null
  rows: FanOutDetail[]
  subject: string | null
  titles: Record<OutlookOutcome, string>
}

const TONES: Record<OutlookOutcome, { icon: string; title: string }> = {
  applied: { icon: "bg-success/10 text-success", title: "text-success" },
  failed: { icon: "bg-destructive/10 text-destructive", title: "text-destructive" },
  unverified: { icon: "bg-warning/15 text-warning-foreground", title: "text-warning-foreground" },
}

export function OutlookWriteOutcome({
  description,
  outcome,
  message,
  url,
  view,
}: {
  description: string | null
  outcome: OutlookOutcome
  message: OutlookMessageReference | null
  url: string | null
  view: OutlookOutcomeView
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
            {outcome === "unverified" ? "Open in Outlook" : view.linkLabel(outcome)}
          </a>
        ) : null}
      </header>
      {hasRows ? (
        <OutlookMessageRows
          className={cn("py-3", body && "border-border border-b")}
          rows={view.rows}
        />
      ) : null}
      {!url && message ? <OutlookMessageRecovery message={message} /> : null}
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

// Compact header rows shared by outcome cards and draft reviews.
export function OutlookMessageRows({
  className,
  rows,
}: {
  className?: string
  rows: FanOutDetail[]
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
