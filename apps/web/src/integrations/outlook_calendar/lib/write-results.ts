// apps/web/src/integrations/outlook_calendar/lib/write-results.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import type { MessageOutcome } from "@/components/tool-ui/message-outcome"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import {
  outlookEventReference,
  type OutlookEventReference,
} from "@/integrations/outlook_calendar/lib/write-args"
import { isNullableString, isOneOf, isRecord } from "@/lib/guards"

export type OutlookCalendarWriteResult = {
  action: string
  detail: string | null
  event: OutlookEventReference | null
  joinUrl: string | null
  outcome: MessageOutcome
  url: string | null
}

const OUTCOMES: ReadonlySet<MessageOutcome> = new Set(["applied", "failed", "unverified"])

// Applied results must name the event; a failed create has none.
export function outlookCalendarWriteResult(value: unknown): OutlookCalendarWriteResult | null {
  if (!isRecord(value) || !isOneOf(OUTCOMES, value["outcome"])) return null
  const event = value["event"] ?? null
  const detail = value["detail"] ?? null
  if (
    (event === null ? value["outcome"] === "applied" : !outlookEventReference(event)) ||
    typeof value["action"] !== "string" ||
    !isNullableString(detail)
  ) {
    return null
  }
  return {
    action: value["action"],
    detail,
    event: outlookEventReference(event),
    joinUrl: safeHttpUrl(nodeText(value["join_url"])),
    outcome: value["outcome"],
    url: safeHttpUrl(nodeText(value["web_link"])),
  }
}
