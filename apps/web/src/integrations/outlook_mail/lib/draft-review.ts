// apps/web/src/integrations/outlook_mail/lib/draft-review.ts

import { outlookMessageReference } from "@/integrations/outlook_mail/lib/write-args"
import { isRecord } from "@/lib/guards"

export function outlookDraftReview(value: unknown) {
  if (!isRecord(value) || !outlookMessageReference(value["message"])) return null
  const draft = value["_draft"]
  if (!isRecord(draft)) return null
  const subject = draft["subject"]
  const body = draft["body"]
  const bodyType = draft["body_type"]
  const from = draft["from"]
  const sender = draft["sender"]
  const to = addresses(draft["to"])
  const cc = addresses(draft["cc"])
  const bcc = addresses(draft["bcc"])
  const replyTo = addresses(draft["reply_to"])
  if (
    typeof subject !== "string" ||
    typeof body !== "string" ||
    (bodyType !== "html" && bodyType !== "text") ||
    typeof from !== "string" ||
    typeof sender !== "string" ||
    !to ||
    !cc ||
    !bcc ||
    !replyTo ||
    to.length + cc.length + bcc.length === 0 ||
    typeof draft["fingerprint"] !== "string"
  )
    return null
  return { subject, body, bodyType, from, sender, to, cc, bcc, replyTo }
}

function addresses(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > 100) return null
  return value.every((item): item is string => typeof item === "string" && item.length > 0)
    ? value
    : null
}
