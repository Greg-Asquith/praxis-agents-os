import { createElement, type ReactNode } from "react"
import type * as ReactModule from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { outlookMessagePreviewQueryOptions } from "@/integrations/outlook_mail/api/message-preview"
import { OutlookMessageRecovery } from "@/integrations/outlook_mail/components/message-recovery"
import { setActiveWorkspaceSlug } from "@/lib/workspace"

vi.mock("react", async (original) => ({
  ...(await original<typeof ReactModule>()),
  useState: () => [true, vi.fn()],
}))
vi.mock("@/components/ui/popover", () => {
  const element = ({ children }: { children?: ReactNode }) => createElement("div", null, children)
  return {
    Popover: element,
    PopoverContent: element,
    PopoverTitle: element,
    PopoverTrigger: element,
  }
})
afterEach(() => {
  vi.unstubAllGlobals()
  setActiveWorkspaceSlug(null)
})
const message = {
  label: "Returned draft subject",
  mailboxId: "returned-mailbox",
  messageId: "returned+/==",
}
function render(client: QueryClient) {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(
        ToolConversationContext,
        { value: "conversation" },
        createElement(OutlookMessageRecovery, { message })
      )
    )
  )
}
describe("returned message recovery through the scoped preview API", () => {
  it("loads the returned identity through the API client and keeps workspace scope", async () => {
    setActiveWorkspaceSlug("acme")
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(
      Response.json({
        kind: "outlook_message",
        content_type: "text",
        content: "Returned message contents",
        meta: { subject: "Returned subject" },
      })
    )
    vi.stubGlobal("fetch", fetch)
    const client = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
    const query = outlookMessagePreviewQueryOptions(
      "conversation",
      message.mailboxId,
      message.messageId
    )
    await client.fetchQuery(query)
    const html = render(client)
    expect(html).toContain("Returned message contents")
    expect(html).toContain("Returned draft subject")
    const call = fetch.mock.calls[0]
    expect(call).toBeDefined()
    if (!call) throw new Error("Expected a preview request")
    const [input, options] = call
    const url = input instanceof Request ? input.url : String(input)
    expect(url).toContain("/integrations/conversations/conversation/previews/outlook_message")
    const request = new URL(url, "https://praxis.test")
    expect(request.searchParams.get("scope_id")).toBe(message.mailboxId)
    expect(request.searchParams.get("ref")).toBe(message.messageId)
    expect(request.searchParams.get("provider_key")).toBe("outlook_mail")
    expect(new Headers(options?.headers).get("X-Workspace")).toBe("acme")
    expect(options?.credentials).toBe("include")
    setActiveWorkspaceSlug("other")
    expect(
      outlookMessagePreviewQueryOptions("conversation", message.mailboxId, message.messageId)
        .queryKey
    ).not.toEqual(query.queryKey)
    client.clear()
  })
  it("reports unavailable if the returned message cannot be resolved", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })))
    const client = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
    await expect(
      client.fetchQuery({
        ...outlookMessagePreviewQueryOptions("conversation", message.mailboxId, message.messageId),
        retry: false,
      })
    ).rejects.toThrow()
    const html = render(client)
    expect(html).toContain("Message unavailable. Check Outlook before trying again.")
    expect(html).not.toContain("outlook.office.com")
    expect(html).not.toContain("returned-mailbox")
    client.clear()
  })
})
