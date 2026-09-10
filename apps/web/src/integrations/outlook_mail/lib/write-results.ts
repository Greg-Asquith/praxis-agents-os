// apps/web/src/integrations/outlook_mail/lib/write-results.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import type { MessageOutcome } from "@/components/tool-ui/message-outcome"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import {
  outlookMessageReference,
  type OutlookMessageReference,
} from "@/integrations/outlook_mail/lib/write-args"
import { isNullableString, isOneOf, isRecord } from "@/lib/guards"

export type OutlookWriteResult = {
  detail: string | null
  errorCode: string | null
  message: OutlookMessageReference | null
  outcome: MessageOutcome
  url: string | null
}

const OUTCOMES: ReadonlySet<MessageOutcome> = new Set(["applied", "failed", "unverified"])

// Applied results must name the message; failures may still link the draft that remains.
export function outlookWriteResult(value: unknown): OutlookWriteResult | null {
  if (!isRecord(value) || !isOneOf(OUTCOMES, value["outcome"])) return null
  const message = value["message"] ?? null
  const detail = value["detail"] ?? null
  const errorCode = value["error_code"] ?? null
  if (
    (message === null ? value["outcome"] === "applied" : !outlookMessageReference(message)) ||
    !isNullableString(detail) ||
    !isNullableString(errorCode)
  ) {
    return null
  }
  return {
    detail,
    errorCode,
    message: outlookMessageReference(message),
    outcome: value["outcome"],
    url: safeHttpUrl(nodeText(value["web_link"])),
  }
}
