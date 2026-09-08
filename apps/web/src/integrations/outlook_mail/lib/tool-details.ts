// apps/web/src/integrations/outlook_mail/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { isRecord } from "@/lib/guards"

const FOLDER_LABELS: Record<string, string> = {
  archive: "Archive",
  deleteditems: "Deleted Items",
  drafts: "Drafts",
  inbox: "Inbox",
  junkemail: "Junk Email",
  sentitems: "Sent Items",
}

export function outlookSearchDetails(args: unknown): FanOutDetail[] {
  const folder = stringArg(args, "folder") ?? "inbox"
  const query = stringArg(args, "query")
  const unreadOnly = isRecord(args) && args["unread_only"] === true
  const limit = numberArg(args, "limit") ?? 10
  return [
    { label: "Folder", value: FOLDER_LABELS[folder.toLowerCase()] ?? folder },
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

function stringArg(args: unknown, key: string): string | null {
  if (!isRecord(args) || typeof args[key] !== "string") return null
  const value = args[key].trim()
  return value || null
}

function numberArg(args: unknown, key: string): number | null {
  return isRecord(args) && typeof args[key] === "number" ? args[key] : null
}
