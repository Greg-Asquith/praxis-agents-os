// apps/web/src/integrations/gmail/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { GmailSendArgs } from "@/integrations/gmail/lib/write-args"
import { compactDetails, numberArg, stringArg } from "@/integrations/tool-details"

export function gmailSearchDetails(args: unknown): FanOutDetail[] {
  const query = stringArg(args, "query")
  const limit = numberArg(args, "limit") ?? 10
  return compactDetails([
    query ? { label: "Search", value: query } : null,
    { label: "Results", value: `Up to ${String(limit)} messages` },
  ])
}

export function gmailRecipientRows(args: GmailSendArgs): FanOutDetail[] {
  return compactDetails([
    { label: "To", value: args.to.join(", ") },
    args.cc.length > 0 ? { label: "Cc", value: args.cc.join(", ") } : null,
    args.bcc.length > 0 ? { label: "Bcc", value: args.bcc.join(", ") } : null,
  ])
}

// The subject follows To so the card summary reads like an email header.
export function gmailSendDetails(args: GmailSendArgs | null): FanOutDetail[] {
  if (!args) {
    return []
  }
  const [to, ...rest] = gmailRecipientRows(args)
  return compactDetails([to ?? null, { label: "Subject", value: args.subject }, ...rest])
}
