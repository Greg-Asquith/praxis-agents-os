import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import type { ToolActivity } from "@/integrations/contract"
import { providerKeyForToolName } from "@/integrations/registry"
import { prefetchProviderPreview } from "@/components/tool-ui/provider-preview-queries"
import { gmailMessagePreviewQueryOptions } from "@/integrations/gmail/api/message-preview"
import { gmailReadPresenter } from "@/integrations/gmail/presenters/read"
import { gmailSearchPresenter } from "@/integrations/gmail/presenters/search"

const NODE = (content: string, ref = "message-1") => ({
  node: "praxis_untrusted" as const,
  source_kind: "gmail_message",
  source_ref: ref,
  content,
})

describe("Gmail tool presenters", () => {
  it("renders search results as inbox rows with links and partial failures", () => {
    const rendered = gmailSearchPresenter.render(
      props({
        id: "search-1",
        kind: "result",
        name: "gmail_search_messages",
        status: "completed",
        args: { query: "from:ada@example.com", limit: 5 },
        result: {
          results: [
            entry({
              messages: [
                {
                  message_id: "message-1",
                  sender: NODE("Ada <ada@example.com>"),
                  to: NODE("team@example.com"),
                  subject: NODE("Quarterly update"),
                  date: NODE("2026-07-22T09:00:00Z"),
                  snippet: NODE("Here is the latest progress."),
                },
              ],
              total: 1,
            }),
            entry(null, {
              provider_key: "gmail",
              display_name: "Support inbox",
              external_id: "support@example.com",
              status: "error",
              error_message: "Access needs to be renewed.",
            }),
          ],
        },
      })
    )
    const html = render(rendered)

    expect(html).toContain("Quarterly update")
    expect(html).toContain("Access needs to be renewed.")
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
  })

  it("opens a search result and fetches its full-message preview exactly once", async () => {
    const fetchPreview = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          kind: "gmail_message",
          content_type: "text",
          content: "Full message",
          meta: { subject: "Quarterly update" },
        }),
        { headers: { "Content-Type": "application/json" }, status: 200 }
      )
    )
    vi.stubGlobal("fetch", fetchPreview)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const selectMessage = prefetchProviderPreview(queryClient, "conversation-1", (id) =>
      gmailMessagePreviewQueryOptions(id, "hello@example.com", "message-1")
    )

    selectMessage()
    await vi.waitFor(() => {
      expect(
        queryClient.getQueryData(
          gmailMessagePreviewQueryOptions("conversation-1", "hello@example.com", "message-1")
            .queryKey
        )
      ).toMatchObject({ content: "Full message" })
    })

    expect(fetchPreview).toHaveBeenCalledOnce()
    expect(String(fetchPreview.mock.calls[0]?.[0])).toContain(
      "/integrations/conversations/conversation-1/previews/gmail_message?provider_key=gmail&ref=message-1&scope_id=hello%40example.com"
    )
    vi.unstubAllGlobals()
  })

  it("returns null when any successful search entry has malformed data", () => {
    expect(
      gmailSearchPresenter.render(
        props({
          id: "search-1",
          kind: "result",
          name: "gmail_search_messages",
          status: "completed",
          result: {
            results: [entry({ messages: [], total: 0 }), entry(null, { provider_key: "gmail" })],
          },
        })
      )
    ).toBeNull()
  })

  it("renders read results as a safe detail view without reply automation", () => {
    const html = render(
      gmailReadPresenter.render(
        props({
          id: "read-1",
          kind: "result",
          name: "gmail_read_message",
          status: "completed",
          args: { message_id: "message-1" },
          result: {
            results: [
              entry({
                message_id: "message-1",
                sender: NODE("Ada <ada@example.com>"),
                to: NODE("team@example.com"),
                subject: NODE("Quarterly update"),
                date: NODE("2026-07-22T09:00:00Z"),
                body: NODE("**Plain external body**"),
                truncated: true,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("**Plain external body**")
    expect(html).not.toContain("<strong>")
    expect(html).not.toContain("Reply")
    expect(html).not.toContain("view=cm")
    expect(html).toContain("shortened to fit")
  })

  it("renders the fetched HTML email in an opaque-origin sandboxed iframe with meta chips", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, enabled: false } },
    })
    client.setQueryData(
      gmailMessagePreviewQueryOptions("conversation-1", "hello@example.com", "message-1").queryKey,
      {
        kind: "gmail_message",
        content_type: "html",
        content: "<b>Rich body</b>",
        meta: {
          subject: "Quarterly update",
          labels: ["Inbox", "Clients"],
          thread_message_count: 3,
        },
      }
    )
    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client },
        createElement(
          ToolConversationContext,
          { value: "conversation-1" },
          createElement(
            "div",
            null,
            gmailReadPresenter.render(
              props({
                id: "read-1",
                kind: "result",
                name: "gmail_read_message",
                status: "completed",
                result: {
                  results: [
                    entry({
                      message_id: "message-1",
                      sender: NODE("Ada <ada@example.com>"),
                      to: NODE("team@example.com"),
                      subject: NODE("Quarterly update"),
                      date: NODE("2026-07-22T09:00:00Z"),
                      body: NODE("Plain fallback body"),
                      truncated: false,
                    }),
                  ],
                },
              })
            )
          )
        )
      )
    )

    // Empty sandbox (opaque origin, no scripts) and an injected CSP are load-bearing.
    expect(html).toContain('sandbox=""')
    expect(html).not.toContain("allow-scripts")
    expect(html).not.toContain("allow-same-origin")
    expect(html).toContain("Content-Security-Policy")
    expect(html).toContain("Rich body")
    // The plain-text fallback is replaced by the full email view.
    expect(html).not.toContain("Plain fallback body")
  })

  it("returns null when any successful read entry has malformed data", () => {
    expect(
      gmailReadPresenter.render(
        props({
          id: "read-1",
          kind: "result",
          name: "gmail_read_message",
          status: "completed",
          result: {
            results: [
              entry({
                message_id: "message-1",
                sender: NODE("Ada <ada@example.com>"),
                to: NODE("team@example.com"),
                subject: NODE("Quarterly update"),
                date: NODE("2026-07-22T09:00:00Z"),
                body: NODE("Plain body"),
                truncated: false,
              }),
              entry(null, { provider_key: "gmail" }),
            ],
          },
        })
      )
    ).toBeNull()
  })

  it("resolves provider keys from tool-name prefixes without the presentations query", () => {
    expect(providerKeyForToolName("gmail_read_message")).toBe("gmail")
    expect(providerKeyForToolName("google_ads_run_report")).toBe("google_ads")
    expect(providerKeyForToolName("airtable_list_records")).toBe("airtable")
    expect(providerKeyForToolName("web_search")).toBeNull()
    expect(providerKeyForToolName("gmailish_tool")).toBeNull()
  })
})

function props(activity: ToolActivity) {
  return {
    activity,
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "gmail",
  }
}

function entry(
  data: unknown,
  overrides: Partial<{
    provider_key: string
    display_name: string
    error_message: string | null
    external_id: string
    status: string
  }> = {}
) {
  return {
    provider_key: "gmail",
    display_name: "Primary inbox",
    external_id: "hello@example.com",
    status: "success",
    data,
    error_message: null,
    ...overrides,
  }
}

function render(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } })
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client }, createElement("div", null, node))
  )
}
