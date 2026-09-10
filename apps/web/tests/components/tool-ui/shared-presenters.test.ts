import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { GmailMessageView } from "@/integrations/gmail/components/message-preview"
import { OutlookMessageView } from "@/integrations/outlook_mail/components/message-preview"

describe("suppressed message previews", () => {
  it.each([GmailMessageView, OutlookMessageView])(
    "shows unavailable search copy and retains saved read bodies",
    (View) => {
      const client = new QueryClient()
      const renderPreview = (search: boolean) =>
        renderToStaticMarkup(
          createElement(
            QueryClientProvider,
            { client },
            createElement(
              ToolConversationContext,
              { value: null },
              createElement(View, {
                mailboxId: "mailbox",
                messageId: "message",
                fallback: search ? "Loading message" : "Saved body",
                ...(search ? { errorFallback: "This message preview is unavailable." } : {}),
              })
            )
          )
        )
      expect(renderPreview(true)).toContain("This message preview is unavailable.")
      expect(renderPreview(true)).not.toContain("Loading message")
      expect(renderPreview(false)).toContain("Saved body")
      expect(client.isFetching()).toBe(0)
    }
  )
})
