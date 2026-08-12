// apps/web/src/integrations/gmail/components/sent-message.tsx

import { MailCheckIcon, MailXIcon } from "lucide-react"

import { HtmlContentFrame } from "@/components/tool-ui/html-content-frame"
import { isRecord } from "@/lib/guards"

export function GmailSendMessage({
  args,
  description,
  state,
}: {
  args: unknown
  description?: string
  state: "sent" | "not-sent"
}) {
  const message = sentMessageArgs(args)
  const sent = state === "sent"
  const Icon = sent ? MailCheckIcon : MailXIcon
  const title = sent ? "Email sent" : "Email not sent"
  return (
    <article aria-label={sent ? "Sent email" : "Unsent email"} className="min-w-0">
      <header className="border-border flex min-w-0 items-start gap-3 border-b pb-3">
        <StatusIcon icon={Icon} sent={sent} />
        <div className="min-w-0 flex-1">
          <p
            className={
              sent ? "text-success text-xs font-medium" : "text-destructive text-xs font-medium"
            }
          >
            {title}
          </p>
          {message ? (
            <h3 className="mt-0.5 text-sm font-medium wrap-break-word">
              {message.subject || "(No subject)"}
            </h3>
          ) : null}
          {description ? (
            <p className="text-muted-foreground mt-1 text-xs leading-relaxed">{description}</p>
          ) : null}
        </div>
      </header>
      {message ? (
        <>
          <dl className="border-border grid min-w-0 gap-2 border-b py-3 text-xs sm:grid-cols-[3rem_1fr]">
            <dt className="text-muted-foreground">To</dt>
            <dd className="min-w-0 wrap-break-word">{message.to.join(", ")}</dd>
            {message.cc.length > 0 ? (
              <>
                <dt className="text-muted-foreground">Cc</dt>
                <dd className="min-w-0 wrap-break-word">{message.cc.join(", ")}</dd>
              </>
            ) : null}
            {message.bcc.length > 0 ? (
              <>
                <dt className="text-muted-foreground">Bcc</dt>
                <dd className="min-w-0 wrap-break-word">{message.bcc.join(", ")}</dd>
              </>
            ) : null}
          </dl>
          <div className="pt-3">
            <HtmlContentFrame
              className="border-border h-80 rounded-lg border"
              html={message.body}
              title={message.subject || "Email body"}
            />
          </div>
        </>
      ) : null}
    </article>
  )
}

function StatusIcon({ icon: Icon, sent }: { icon: typeof MailCheckIcon; sent: boolean }) {
  return (
    <span
      className={
        sent
          ? "bg-success/10 text-success flex size-8 shrink-0 items-center justify-center rounded-full"
          : "bg-destructive/10 text-destructive flex size-8 shrink-0 items-center justify-center rounded-full"
      }
    >
      <Icon className="size-4" />
    </span>
  )
}

// eslint-disable-next-line react-refresh/only-export-components -- The send presenter shares this parser.
export function sentMessageArgs(value: unknown) {
  if (
    !isRecord(value) ||
    !Array.isArray(value["to"]) ||
    !value["to"].every((item) => typeof item === "string") ||
    typeof value["subject"] !== "string" ||
    typeof value["body_html"] !== "string"
  ) {
    return null
  }
  return {
    bcc: stringList(value["bcc"]),
    body: value["body_html"],
    cc: stringList(value["cc"]),
    subject: value["subject"],
    to: value["to"],
  }
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : []
}
