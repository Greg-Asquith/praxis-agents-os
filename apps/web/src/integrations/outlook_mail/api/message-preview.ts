// apps/web/src/integrations/outlook_mail/api/message-preview.ts

import { providerPreviewQueryOptions } from "@/components/tool-ui/provider-preview-queries"

export function outlookMessagePreviewQueryOptions(
  conversationId: string | null,
  mailboxId: string,
  messageId: string
) {
  return providerPreviewQueryOptions({
    conversationId,
    providerKey: "outlook_mail",
    kind: "outlook_message",
    scopeId: mailboxId,
    ref: messageId,
  })
}
