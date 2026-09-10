// apps/web/src/integrations/outlook_mail/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type {
  OutlookDraftArgs,
  OutlookForwardArgs,
  OutlookMoveArgs,
  OutlookRecipients,
  OutlookReplyArgs,
  OutlookSendArgs,
  OutlookUpdateArgs,
} from "@/integrations/outlook_mail/lib/write-args"
import { booleanArg, numberArg, stringArg } from "@/integrations/tool-details"

const FOLDER_LABELS: Record<string, string> = {
  archive: "Archive",
  deleteditems: "Deleted Items",
  drafts: "Drafts",
  inbox: "Inbox",
  junkemail: "Junk Email",
  sentitems: "Sent Items",
}

function outlookFolderLabel(folder: string): string {
  return FOLDER_LABELS[folder.toLowerCase()] ?? folder
}

export function outlookSearchDetails(args: unknown): FanOutDetail[] {
  const folder = stringArg(args, "folder") ?? "inbox"
  const query = stringArg(args, "query")
  const unreadOnly = booleanArg(args, "unread_only") === true
  const limit = numberArg(args, "limit") ?? 10
  return [
    { label: "Folder", value: outlookFolderLabel(folder) },
    ...(query ? [{ label: "Search", value: query }] : []),
    ...(unreadOnly ? [{ label: "Filter", value: "Unread only" }] : []),
    { label: "Results", value: `Up to ${String(limit)} messages` },
  ]
}

export function outlookPeopleDetails(args: unknown): FanOutDetail[] {
  const query = stringArg(args, "query")
  const limit = numberArg(args, "limit") ?? 10
  return [
    ...(query ? [{ label: "Name", value: query }] : []),
    { label: "Results", value: `Up to ${String(limit)} people` },
  ]
}

export function outlookRecipientRows(args: OutlookRecipients): FanOutDetail[] {
  return [
    ...(args.to && args.to.length > 0 ? [{ label: "To", value: args.to.join(", ") }] : []),
    ...(args.cc && args.cc.length > 0 ? [{ label: "Cc", value: args.cc.join(", ") }] : []),
    ...(args.bcc && args.bcc.length > 0 ? [{ label: "Bcc", value: args.bcc.join(", ") }] : []),
  ]
}

export function outlookSendDetails(args: OutlookSendArgs | null): FanOutDetail[] {
  return args ? withSubject(outlookRecipientRows(args), args.subject) : []
}

export function outlookReplyDetails(args: OutlookReplyArgs | null): FanOutDetail[] {
  return args
    ? [
        { label: "Source message", value: args.message.label },
        { label: "Reply all", value: args.replyAll ? "Yes" : "No" },
      ]
    : []
}

export function outlookForwardDetails(args: OutlookForwardArgs | null): FanOutDetail[] {
  return args
    ? [
        { label: "Source message", value: args.message.label },
        { label: "To", value: args.to.join(", ") },
      ]
    : []
}

export function outlookDraftRows(args: OutlookDraftArgs): FanOutDetail[] {
  const kind = args.replyTo
    ? [
        { label: "Source message", value: args.replyTo.label },
        { label: "Draft", value: args.replyAll ? "Reply all" : "Reply" },
      ]
    : []
  const inherited = args.replyTo
    ? (["to", "cc", "bcc"] as const)
        .filter((key) => args[key] === null)
        .map((key) => ({
          label: key === "to" ? "To" : key === "cc" ? "Cc" : "Bcc",
          value: "Keep reply recipients from Outlook",
        }))
    : []
  return [...kind, ...outlookRecipientRows(args), ...inherited]
}

export function outlookDraftDetails(args: OutlookDraftArgs | null): FanOutDetail[] {
  return args ? withSubject(outlookDraftRows(args), args.subject) : []
}

export function outlookMoveDetails(args: OutlookMoveArgs | null): FanOutDetail[] {
  return args
    ? [
        { label: "Source message", value: args.message.label },
        { label: "Folder", value: outlookFolderLabel(args.destinationFolder) },
      ]
    : []
}

export function outlookUpdateDetails(args: OutlookUpdateArgs | null): FanOutDetail[] {
  if (!args) return []
  return [
    { label: "Source message", value: args.message.label },
    ...(args.isRead === null ? [] : [{ label: "Read", value: args.isRead ? "Read" : "Unread" }]),
    ...(args.flagged === null
      ? []
      : [{ label: "Flag", value: args.flagged ? "Flagged" : "Not flagged" }]),
  ]
}

// The subject follows To so the card summary reads like an email header.
function withSubject(rows: FanOutDetail[], subject: string | null): FanOutDetail[] {
  if (!subject) return rows
  const [to, ...rest] = rows
  return to?.label === "To"
    ? [to, { label: "Subject", value: subject }, ...rest]
    : [{ label: "Subject", value: subject }, ...rows]
}
