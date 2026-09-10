// apps/web/src/integrations/gmail/lib/write-args.ts

import { isRecord } from "@/lib/guards"

export type GmailSendArgs = {
  bcc: string[]
  body: string
  cc: string[]
  subject: string
  to: string[]
}

export function parseGmailSendArgs(value: unknown): GmailSendArgs | null {
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

export function parseGmailSentMessageId(value: unknown): string | null {
  return isRecord(value) && typeof value["message_id"] === "string" ? value["message_id"] : null
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : []
}
