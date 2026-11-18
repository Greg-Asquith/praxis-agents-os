// apps/web/src/integrations/do-not-email.ts

import { isRecord } from "@/lib/guards"

const RECIPIENT_KEYS = ["to", "cc", "bcc"] as const

// Recipients the server found on the Do Not Email list, read against the card's current edits.
export function doNotEmailProblem(args: unknown, fix: string): string | null {
  if (!isRecord(args)) return null
  const listed = stringList(args["_do_not_email"])
  if (listed.length === 0) return null
  // A saved draft's recipients sit in its review snapshot, not in the arguments.
  const source = isRecord(args["_draft"]) ? args["_draft"] : args
  const current = new Set(
    RECIPIENT_KEYS.flatMap((key) => stringList(source[key])).map((value) =>
      value.trim().toLowerCase()
    )
  )
  const remaining = listed.filter((address) => current.has(address))
  if (remaining.length === 0) return null
  const last = remaining.slice(-1).join("")
  const names = remaining.length === 1 ? last : `${remaining.slice(0, -1).join(", ")} and ${last}`
  return `${names} ${remaining.length === 1 ? "is" : "are"} on this workspace's Do Not Email list. ${fix}`
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : []
}
