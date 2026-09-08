// apps/web/src/integrations/outlook_mail/lib/write-args.ts

import { isRecord } from "@/lib/guards"

export type OutlookMessageReference = {
  label: string
  mailboxId: string
  messageId: string
}

export type OutlookRecipients = {
  bcc: string[] | null
  cc: string[] | null
  to: string[] | null
}

export type OutlookSendArgs = OutlookRecipients & { body: string; subject: string; to: string[] }
export type OutlookReplyArgs = { body: string; message: OutlookMessageReference; replyAll: boolean }
export type OutlookForwardArgs = { body: string; message: OutlookMessageReference; to: string[] }
export type OutlookDraftArgs = OutlookRecipients & {
  body: string
  replyAll: boolean
  replyTo: OutlookMessageReference | null
  subject: string | null
}
export type OutlookMoveArgs = { destinationFolder: string; message: OutlookMessageReference }
export type OutlookUpdateArgs = {
  flagged: boolean | null
  isRead: boolean | null
  message: OutlookMessageReference
}

export function outlookMessageReference(value: unknown): OutlookMessageReference | null {
  if (
    !isRecord(value) ||
    value["entity_kind"] !== "outlook_message" ||
    typeof value["mailbox_id"] !== "string" ||
    !value["mailbox_id"] ||
    typeof value["message_id"] !== "string" ||
    !value["message_id"]
  ) {
    return null
  }
  const label = typeof value["label"] === "string" ? value["label"].trim() : ""
  return {
    label: label || "Outlook message",
    mailboxId: value["mailbox_id"],
    messageId: value["message_id"],
  }
}

export function outlookSendArgs(value: unknown): OutlookSendArgs | null {
  if (!isRecord(value)) return null
  const to = requiredRecipients(value["to"])
  const cc = recipients(value["cc"])
  const bcc = recipients(value["bcc"])
  const subject = requiredText(value["subject"])
  const body = optionalText(value["body_html"])
  if (!to || !cc || !bcc || subject === null || body === null) return null
  return { bcc, body, cc, subject, to }
}

export function outlookReplyArgs(value: unknown): OutlookReplyArgs | null {
  if (!isRecord(value)) return null
  const message = outlookMessageReference(value["message"])
  const body = optionalText(value["body_html"])
  const replyAll = optionalFlag(value["reply_all"])
  if (!message || body === null || replyAll === undefined) return null
  return { body, message, replyAll: replyAll ?? false }
}

export function outlookForwardArgs(value: unknown): OutlookForwardArgs | null {
  if (!isRecord(value)) return null
  const message = outlookMessageReference(value["message"])
  const to = requiredRecipients(value["to"])
  const body = optionalText(value["body_html"])
  if (!message || !to || body === null) return null
  return { body, message, to }
}

export function outlookDraftArgs(value: unknown): OutlookDraftArgs | null {
  if (!isRecord(value)) return null
  const replyTo = isAbsent(value["reply_to"]) ? null : outlookMessageReference(value["reply_to"])
  const to = isAbsent(value["to"]) ? null : requiredRecipients(value["to"])
  const subject = isAbsent(value["subject"]) ? null : requiredText(value["subject"])
  const cc = recipients(value["cc"])
  const bcc = recipients(value["bcc"])
  const body = optionalText(value["body_html"])
  const replyAll = optionalFlag(value["reply_all"])
  if (
    (replyTo === null && !isAbsent(value["reply_to"])) ||
    (to === null && !isAbsent(value["to"])) ||
    (subject === null && !isAbsent(value["subject"])) ||
    !cc ||
    !bcc ||
    body === null ||
    replyAll === undefined
  ) {
    return null
  }
  return {
    bcc: replyTo && isAbsent(value["bcc"]) ? null : bcc,
    body,
    cc: replyTo && isAbsent(value["cc"]) ? null : cc,
    replyAll: replyAll ?? false,
    replyTo,
    subject,
    to,
  }
}

// Mirrors the server's draft rules so the operator sees the reason before resume.
export function validateOutlookDraftArgs(value: unknown): string | null {
  const args = outlookDraftArgs(value)
  if (!args) return null
  if (args.replyTo) {
    return args.to !== null || args.subject !== null
      ? "A reply draft cannot set To or Subject."
      : null
  }
  if (args.to === null || args.subject === null) return "A new draft needs To and Subject."
  return args.replyAll ? "Reply all needs a message to reply to." : null
}

export function outlookMoveArgs(value: unknown): OutlookMoveArgs | null {
  if (!isRecord(value)) return null
  const message = outlookMessageReference(value["message"])
  const destinationFolder = requiredText(value["destination_folder"])
  if (!message || destinationFolder === null) return null
  return { destinationFolder: destinationFolder.trim(), message }
}

export function outlookUpdateArgs(value: unknown): OutlookUpdateArgs | null {
  if (!isRecord(value)) return null
  const message = outlookMessageReference(value["message"])
  const isRead = optionalFlag(value["is_read"])
  const flagged = optionalFlag(value["flagged"])
  if (!message || isRead === undefined || flagged === undefined) return null
  return { flagged, isRead, message }
}

export function validateOutlookUpdateArgs(value: unknown): string | null {
  const args = outlookUpdateArgs(value)
  return args?.isRead === null && args.flagged === null
    ? "Set Read or Flagged to update a message."
    : null
}

function isAbsent(value: unknown): boolean {
  return value === null || value === undefined
}

// Callers preserve inheritance for reply drafts after validating the list shape.
function recipients(value: unknown): string[] | null {
  if (isAbsent(value)) return []
  if (!Array.isArray(value)) return null
  const items = value.filter(
    (item): item is string => typeof item === "string" && Boolean(item.trim())
  )
  return items.length === value.length ? items : null
}

function requiredRecipients(value: unknown): string[] | null {
  const list = recipients(value)
  return list?.length ? list : null
}

function requiredText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null
}

function optionalText(value: unknown): string | null {
  return isAbsent(value) ? "" : typeof value === "string" ? value : null
}

// Returns undefined for values that are neither booleans nor absent.
function optionalFlag(value: unknown): boolean | null | undefined {
  return isAbsent(value) ? null : typeof value === "boolean" ? value : undefined
}
