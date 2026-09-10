// apps/web/src/components/tool-ui/message-outcome-icons.ts

import { MailCheckIcon, MailQuestionIcon, MailXIcon, type LucideIcon } from "lucide-react"

import type { MessageOutcome } from "@/components/tool-ui/message-outcome"

export const MAIL_OUTCOME_ICONS: Record<MessageOutcome, LucideIcon> = {
  applied: MailCheckIcon,
  failed: MailXIcon,
  unverified: MailQuestionIcon,
}

export function sameOutcomeIcon(icon: LucideIcon): Record<MessageOutcome, LucideIcon> {
  return { applied: icon, failed: icon, unverified: icon }
}
