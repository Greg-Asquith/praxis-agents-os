// apps/web/src/integrations/outlook_mail/lib/messages.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import { relativeDateTime } from "@/lib/format"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export type OutlookMessage = {
  mailboxId: string
  messageId: string
  subject: string
  sender: string
  receivedAt: string | null
  preview: string
  unread: boolean
  important: boolean
  hasAttachments: boolean
}

export type OutlookAttachment = {
  name: string
  sizeBytes: number | null
}

export type OutlookMessageDetail = OutlookMessage & {
  body: string
  to: string
  truncated: boolean
  attachments: OutlookAttachment[]
}

export function messageDate(message: OutlookMessage): string {
  return message.receivedAt ? relativeDateTime(message.receivedAt) : "Unknown date"
}

// Shows "Name <address>" like Gmail headers, or just the address when no name exists.
function contact(value: unknown): string | null {
  if (!isRecord(value)) return null
  const address = nodeText(value["address"])
  if (address === null) return null
  const name = nodeText(value["name"])?.trim()
  return name && name !== address ? `${name} <${address}>` : address
}

function attachment(value: unknown): OutlookAttachment | null {
  if (!isRecord(value)) return null
  const name = nodeText(value["name"])
  if (name === null) return null
  const size = value["size_bytes"]
  return { name, sizeBytes: isNonNegativeInteger(size) ? size : null }
}

function message(value: unknown): OutlookMessage | null {
  if (!isRecord(value) || !isRecord(value["reference"])) return null
  const ref = value["reference"]
  const subject = nodeText(value["subject"])
  const sender = contact(value["from"])
  const preview = nodeText(value["preview"])
  if (
    ref["entity_kind"] !== "outlook_message" ||
    typeof ref["mailbox_id"] !== "string" ||
    typeof ref["message_id"] !== "string" ||
    subject === null ||
    sender === null ||
    preview === null ||
    typeof value["is_read"] !== "boolean" ||
    typeof value["has_attachments"] !== "boolean" ||
    (value["received_at"] !== null && typeof value["received_at"] !== "string")
  )
    return null
  return {
    mailboxId: ref["mailbox_id"],
    messageId: ref["message_id"],
    subject,
    sender,
    preview,
    receivedAt: value["received_at"] ?? null,
    unread: !value["is_read"],
    important: value["importance"] === "high",
    hasAttachments: value["has_attachments"],
  }
}

export function searchMessages(value: unknown): OutlookMessage[] | null {
  if (!isRecord(value) || !Array.isArray(value["messages"])) return null
  const messages = value["messages"].map(message)
  return messages.every((item) => item !== null) ? messages : null
}

export function readMessage(value: unknown): OutlookMessageDetail | null {
  const summary = message(value)
  if (
    !summary ||
    !isRecord(value) ||
    !Array.isArray(value["to"]) ||
    !Array.isArray(value["attachments"]) ||
    typeof value["truncated"] !== "boolean"
  )
    return null
  const body = nodeText(value["body"])
  const recipients = value["to"].map(contact)
  const attachments = value["attachments"].map(attachment)
  if (
    body === null ||
    recipients.some((item) => item === null) ||
    !attachments.every((item): item is OutlookAttachment => item !== null)
  )
    return null
  return { ...summary, body, to: recipients.join(", "), attachments, truncated: value["truncated"] }
}
