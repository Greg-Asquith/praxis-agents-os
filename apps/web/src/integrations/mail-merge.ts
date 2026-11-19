// apps/web/src/integrations/mail-merge.ts

import { pluralize } from "@/lib/format"
import { isOneOf, isRecord } from "@/lib/guards"

type RowStatus = "ready" | "needs_attention" | "skipped"
type SkipReason = "duplicate" | "sender" | "do_not_email"

export const SKIP_REASON_TEXT: Record<SkipReason, string> = {
  do_not_email: "On the Do Not Email list",
  duplicate: "Already in the list",
  sender: "Your own address",
}

export type MergeRecipient = {
  email: string
  firstName: string
  lastName: string
  fields: Record<string, string>
}

// The server's check of one row; null when the row changed after the check.
export type RowCheck = {
  status: RowStatus
  problems: string[]
  warnings: string[]
  skipReason: SkipReason | null
}

type MergeTest = { sentTo: string; recipient: string; sentAt: string }

export type MailMergeArgs = {
  subject: string
  bodyHtml: string
  fallbacks: Record<string, string>
  recipients: MergeRecipient[]
  checks: (RowCheck | null)[]
  sender: string | null
  budget: { remaining: number } | null
  estimatedFinish: string | null
  needsReconnect: boolean
  templateProblem: string | null
  test: MergeTest | null
  // True until a test of the current subject, body and fallbacks has been sent.
  needsTest: boolean
}

export type MailMergeResult = {
  mergeId: string
  sender: string
  sendingTo: number
  estimatedFinish: string | null
}

const STATUSES: ReadonlySet<RowStatus> = new Set(["ready", "needs_attention", "skipped"])
const SKIP_REASONS: ReadonlySet<SkipReason> = new Set(["duplicate", "sender", "do_not_email"])
const PLACEHOLDER = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\|([^{}]*))?\}\}/g
export function parseMailMergeArgs(value: unknown): MailMergeArgs | null {
  if (
    !isRecord(value) ||
    typeof value["subject"] !== "string" ||
    typeof value["body_html"] !== "string" ||
    !Array.isArray(value["recipients"])
  )
    return null
  const recipients: MergeRecipient[] = []
  for (const item of value["recipients"]) {
    if (!isRecord(item) || typeof item["email"] !== "string") return null
    recipients.push({
      email: item["email"],
      firstName: text(item["first_name"]),
      lastName: text(item["last_name"]),
      fields: textRecord(item["fields"]),
    })
  }
  const evidence = isRecord(value["_merge"]) ? value["_merge"] : {}
  // A check follows its address, so removing or reordering rows keeps the others' checks.
  const checked = new Map<string, unknown[]>()
  for (const item of Array.isArray(evidence["recipients"]) ? evidence["recipients"] : []) {
    if (!isRecord(item) || typeof item["email"] !== "string") continue
    checked.set(item["email"], [...(checked.get(item["email"]) ?? []), item])
  }
  const mailbox = isRecord(value["_mailbox"]) ? value["_mailbox"] : {}
  const budget = isRecord(evidence["budget"]) ? evidence["budget"] : null
  const fallbacks = textRecord(value["fallbacks"])
  return {
    subject: value["subject"],
    bodyHtml: value["body_html"],
    fallbacks,
    recipients,
    checks: recipients.map((recipient) =>
      rowCheck(checked.get(recipient.email.trim().toLowerCase())?.shift())
    ),
    sender: typeof mailbox["address"] === "string" ? mailbox["address"] : null,
    budget:
      budget && typeof budget["remaining"] === "number" ? { remaining: budget["remaining"] } : null,
    estimatedFinish:
      typeof evidence["estimated_finish"] === "string" ? evidence["estimated_finish"] : null,
    needsReconnect: evidence["needs_reconnect"] === true,
    templateProblem:
      typeof evidence["template_problem"] === "string" ? evidence["template_problem"] : null,
    test: parseTest(value["_test"]),
    needsTest: !matchesReviewed(value, value["_reviewed"]),
  }
}

export function parseMailMergeResult(value: unknown): MailMergeResult | null {
  if (
    !isRecord(value) ||
    typeof value["merge_id"] !== "string" ||
    typeof value["sender"] !== "string" ||
    typeof value["sending_to"] !== "number"
  )
    return null
  return {
    mergeId: value["merge_id"],
    sender: value["sender"],
    sendingTo: value["sending_to"],
    estimatedFinish:
      typeof value["estimated_finish"] === "string" ? value["estimated_finish"] : null,
  }
}

export function readyCount(args: MailMergeArgs): number {
  return args.checks.filter((check) => check?.status === "ready").length
}

/** A changed row may be ready; the server checks it at the next test or approval. */
export function mayHaveReadyRow(args: MailMergeArgs): boolean {
  return args.checks.some((check) => check === null || check.status === "ready")
}

/** Why Approve is blocked, or null. The server enforces the test on its own. */
export function mailMergeProblem(args: MailMergeArgs | null, provider: string): string | null {
  if (!args) return null
  if (args.templateProblem) return args.templateProblem
  if (args.needsReconnect)
    return `Reconnect ${provider} so Praxis can send mail merges, then send the test.`
  if (!mayHaveReadyRow(args)) return "No recipient is ready to send to."
  if (args.needsTest)
    return args.test
      ? "You changed the email after your test. Send a new test before approving."
      : "Send yourself a test of this email before approving."
  return null
}

export function mailMergePrompt(args: MailMergeArgs): string {
  const count = readyCount(args)
  const from = args.sender ? ` from ${args.sender}` : ""
  const finish = args.estimatedFinish
    ? `, finishing around ${finishText(args.estimatedFinish)}`
    : ""
  return `Send ${countOf(count, "personal email")}${from}, one every few seconds${finish}.`
}

/** A count with its noun, such as "1 email" or "212 emails". */
export function countOf(count: number, singular: string): string {
  return `${count.toLocaleString()} ${pluralize(count, singular)}`
}

export function finishText(value: string): string {
  const date = new Date(value)
  const sameDay = date.toDateString() === new Date().toDateString()
  return new Intl.DateTimeFormat(undefined, {
    ...(sameDay ? {} : { weekday: "long" }),
    hour: "numeric",
    minute: "2-digit",
  }).format(date)
}

export const STANDARD_COLUMNS = ["email", "first_name", "last_name"] as const

/** Columns beyond email and names: any a recipient has, or the subject, body or fallbacks name. */
export function extraColumns(args: MailMergeArgs): string[] {
  const named = [
    ...args.recipients.flatMap((recipient) => Object.keys(recipient.fields)),
    ...[...`${args.subject}\n${args.bodyHtml}`.matchAll(PLACEHOLDER)].map(
      (match) => match[1] ?? ""
    ),
    ...Object.keys(args.fallbacks),
  ]
  const standard: ReadonlySet<string> = new Set(STANDARD_COLUMNS)
  return [...new Set(named)].filter((name) => name && !standard.has(name))
}

export function recipientValues(recipient: MergeRecipient): Record<string, string> {
  return {
    ...recipient.fields,
    email: recipient.email,
    first_name: recipient.firstName,
    last_name: recipient.lastName,
  }
}

/** Fills placeholders as the server does, for the preview only; an inline fallback is template text. */
export function fillMergeTemplate(
  template: string,
  values: Record<string, string>,
  fallbacks: Record<string, string>,
  html: boolean
): { text: string; missing: string[] } {
  const missing: string[] = []
  const text = template.replace(PLACEHOLDER, (_match, name: string, inline?: string) => {
    // A placeholder such as {{constructor}} must not read an inherited property.
    const value = (Object.hasOwn(values, name) ? (values[name] ?? "") : "").trim()
    if (value) return html ? escapeHtml(value) : value
    if (inline?.trim()) return inline.trim()
    const fallback = (Object.hasOwn(fallbacks, name) ? (fallbacks[name] ?? "") : "").trim()
    if (fallback) return html ? escapeHtml(fallback) : fallback
    missing.push(name)
    return ""
  })
  return { text, missing: [...new Set(missing)] }
}

function rowCheck(value: unknown): RowCheck | null {
  if (!isRecord(value) || !isOneOf(STATUSES, value["status"])) return null
  return {
    status: value["status"],
    problems: stringList(value["problems"]),
    warnings: stringList(value["warnings"]),
    skipReason: isOneOf(SKIP_REASONS, value["skip_reason"]) ? value["skip_reason"] : null,
  }
}

function parseTest(value: unknown): MergeTest | null {
  if (
    !isRecord(value) ||
    typeof value["sent_to"] !== "string" ||
    typeof value["recipient"] !== "string" ||
    typeof value["sent_at"] !== "string"
  )
    return null
  return { sentTo: value["sent_to"], recipient: value["recipient"], sentAt: value["sent_at"] }
}

// Mirrors the server: approval needs these three exactly as the last test sent them.
function matchesReviewed(current: Record<string, unknown>, reviewed: unknown): boolean {
  if (!isRecord(reviewed)) return false
  return (
    current["subject"] === reviewed["subject"] &&
    current["body_html"] === reviewed["body_html"] &&
    sameRecord(current["fallbacks"], reviewed["fallbacks"])
  )
}

function sameRecord(left: unknown, right: unknown): boolean {
  if (left === undefined || left === null || right === undefined || right === null)
    return (left ?? null) === (right ?? null)
  if (!isRecord(left) || !isRecord(right)) return false
  const keys = Object.keys(left)
  return keys.length === Object.keys(right).length && keys.every((key) => left[key] === right[key])
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;")
}

function text(value: unknown): string {
  return typeof value === "string" ? value : ""
}

// Booleans read as the server sends them, so an edited row keeps "Yes" and "No".
function textRecord(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {}
  return Object.fromEntries(
    Object.entries(value).flatMap(([key, item]) => {
      if (typeof item === "boolean") return [[key, item ? "Yes" : "No"]]
      return typeof item === "string" || typeof item === "number" ? [[key, String(item)]] : []
    })
  )
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : []
}
