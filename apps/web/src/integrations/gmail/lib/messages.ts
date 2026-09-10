// apps/web/src/integrations/gmail/lib/messages.ts

import { isUntrustedNode, nodeText, type UntrustedNode } from "@/components/tool-ui/untrusted-node"
import { isRecord } from "@/lib/guards"

export type GmailMessageSummary = {
  date: string
  messageId: string
  sender: string
  snippet: string
  subject: string
}

export type GmailMessage = {
  body: string | UntrustedNode
  date: string
  messageId: string
  sender: string
  subject: string
  to: string
  truncated: boolean
}

export function parseGmailSearchResult(value: unknown): GmailMessageSummary[] | null {
  if (!isRecord(value) || !Array.isArray(value["messages"]) || typeof value["total"] !== "number") {
    return null
  }
  const messages = value["messages"].map(parseSummary)
  return messages.every((message): message is GmailMessageSummary => message !== null)
    ? messages
    : null
}

export function parseGmailMessage(value: unknown): GmailMessage | null {
  if (
    !isRecord(value) ||
    typeof value["message_id"] !== "string" ||
    typeof value["truncated"] !== "boolean"
  ) {
    return null
  }
  const sender = nodeText(value["sender"])
  const subject = nodeText(value["subject"])
  const to = nodeText(value["to"])
  const date = nodeText(value["date"])
  const body = value["body"]
  if (
    sender === null ||
    subject === null ||
    to === null ||
    date === null ||
    (typeof body !== "string" && !isUntrustedNode(body))
  ) {
    return null
  }
  return {
    body,
    date,
    messageId: value["message_id"],
    sender,
    subject,
    to,
    truncated: value["truncated"],
  }
}

function parseSummary(value: unknown): GmailMessageSummary | null {
  if (!isRecord(value) || typeof value["message_id"] !== "string") {
    return null
  }
  const sender = nodeText(value["sender"])
  const subject = nodeText(value["subject"])
  const date = nodeText(value["date"])
  const snippet = nodeText(value["snippet"])
  if (sender === null || subject === null || date === null || snippet === null) {
    return null
  }
  return { date, messageId: value["message_id"], sender, snippet, subject }
}
