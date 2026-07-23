import { createElement, isValidElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { parseConversationMessages } from "@/features/conversations/message-parts/parse"
import {
  agentStreamReducer,
  initialAgentStreamState,
} from "@/features/conversations/stream/reducer"
import type { ConversationMessage } from "@/features/conversations/types"
import type { ToolActivity } from "@/integrations/contract"
import {
  integrationToolRowPresenters,
  loadIntegrationUiModules,
  providerKeyForToolName,
} from "@/integrations/registry"
import { gmailReadPresenter } from "@/integrations/gmail/read-presenter"
import { gmailSearchMessageSelectHandler } from "@/integrations/gmail/search-interaction"
import { gmailSearchPresenter } from "@/integrations/gmail/search-presenter"
import { gmailSendPresenter } from "@/integrations/gmail/send-presenter"
import { gmailSendDetails } from "@/integrations/gmail/tool-details"
import { gmailMessagePreviewQueryOptions } from "@/integrations/gmail/api"

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
              connection_id: "connection-2",
              display_name: "Support inbox",
              external_id: "support@example.com",
              status: "failed",
              error_message: "Access needs to be renewed.",
            }),
          ],
        },
      })
    )
    const html = render(rendered)

    expect(html).toContain("Quarterly update")
    expect(html).toContain("Search Gmail")
    expect(html).toContain("from:ada@example.com")
    expect(html).toContain("Up to 5 messages")
    expect(html).toContain("Primary inbox")
    expect(html).toContain("hello@example.com")
    expect(html).toContain("Ada &lt;ada@example.com&gt;")
    expect(html).not.toContain("Open in Gmail")
    expect(html).not.toContain("Gmail Message")
    expect(html).toContain("Access needs to be renewed.")
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
    expect(html).not.toContain("max-w-3xl")
    expect(html).toContain("max-h-[min(32rem,60vh)]")
    expect(html).toContain('role="list"')
  })

  it("renders a running search as the pending kit state", () => {
    const html = render(
      gmailSearchPresenter.render(
        props({ id: "search-1", kind: "call", name: "gmail_search_messages", status: "running" })
      )
    )
    expect(html).toContain("Searching mailboxes…")
    expect(html).toContain('aria-busy="true"')
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
    const onOpen = vi.fn()
    const selectMessage = gmailSearchMessageSelectHandler({
      connectionId: "connection-1",
      messageId: "message-1",
      onOpen,
      queryClient,
    })

    selectMessage()
    await vi.waitFor(() => {
      expect(
        queryClient.getQueryData(
          gmailMessagePreviewQueryOptions("connection-1", "message-1").queryKey
        )
      ).toMatchObject({ content: "Full message" })
    })

    expect(onOpen).toHaveBeenCalledOnce()
    expect(fetchPreview).toHaveBeenCalledOnce()
    expect(String(fetchPreview.mock.calls[0]?.[0])).toContain(
      "/integrations/connections/connection-1/previews/gmail_message?ref=message-1"
    )
    vi.unstubAllGlobals()
  })

  it("returns null for unexpected search payloads", () => {
    expect(
      gmailSearchPresenter.render(
        props({
          id: "search-1",
          kind: "result",
          name: "gmail_search_messages",
          status: "completed",
          result: { results: [{ status: "success" }] },
        })
      )
    ).toBeNull()
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
            results: [
              entry({ messages: [], total: 0 }),
              entry(null, { connection_id: "connection-2" }),
            ],
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

    expect(html).toContain("External Content")
    expect(html).toContain("Read Gmail Message")
    expect(html).toContain("Primary inbox")
    expect(html).toContain("**Plain external body**")
    expect(html).not.toContain("<strong>")
    expect(html).not.toContain("Reply")
    expect(html).not.toContain("view=cm")
    expect(html).toContain("shortened to fit")
  })

  it("renders a running read as a single pending state", () => {
    const html = render(
      gmailReadPresenter.render(
        props({ id: "read-1", kind: "call", name: "gmail_read_message", status: "running" })
      )
    )

    expect(html).toContain("Reading message…")
    expect(html.match(/aria-busy="true"/g)).toHaveLength(1)
  })

  it("renders the fetched HTML email in an opaque-origin sandboxed iframe with meta chips", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, enabled: false } },
    })
    client.setQueryData(gmailMessagePreviewQueryOptions("connection-1", "message-1").queryKey, {
      kind: "gmail_message",
      content_type: "html",
      content: "<b>Rich body</b>",
      meta: {
        subject: "Quarterly update",
        labels: ["Inbox", "Clients"],
        thread_message_count: 3,
      },
    })
    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client },
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

    // Empty sandbox (opaque origin, no scripts) and an injected CSP are load-bearing.
    expect(html).toContain('sandbox=""')
    expect(html).not.toContain("allow-scripts")
    expect(html).not.toContain("allow-same-origin")
    expect(html).toContain("Content-Security-Policy")
    expect(html).toContain("Rich body")
    expect(html).toContain("Inbox")
    expect(html).toContain("Clients")
    expect(html).toContain("Thread · 3 Messages")
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
              entry(null, { connection_id: "connection-2" }),
            ],
          },
        })
      )
    ).toBeNull()
  })

  it("renders an email-shaped approval surface with the existing controls contract", () => {
    const onDecisionChange = vi.fn()
    const controls = {
      decision: { decision: "pending" as const, edits: {}, message: "" as const },
      error: null,
      onDecisionChange,
      onRetry: vi.fn(),
      pendingCount: 1,
      submitting: false,
    }
    const rendered = gmailSendPresenter.render(
      props(
        {
          id: "send-1",
          kind: "approval",
          name: "gmail_send_message",
          status: "awaiting_approval",
          args: {
            to: ["client@example.com"],
            subject: "Project update",
            body_text: "The work is complete.",
            cc: [],
            bcc: [],
          },
        },
        controls
      )
    )

    expect(isValidElement(rendered)).toBe(true)
    if (isValidElement<{ controls: unknown }>(rendered)) {
      expect(rendered.type).toBe(ToolApprovalDecisionCard)
      expect(rendered.props.controls).toBe(controls)
    }
    const html = render(rendered)
    expect(html).toContain("Review email before sending")
    expect(html).toContain("client@example.com")
    expect(html).toContain("Project update")
    expect(html).toContain("The work is complete.")
    expect(html).toContain("Approve &amp; Send")
    expect(html).toContain("Decline")
  })

  it("keeps long send inputs in the details popover but out of the header summary", () => {
    expect(
      gmailSendDetails({
        to: ["client@example.com"],
        subject: "Project update",
        body_text: "A long message body",
      })
    ).toEqual([
      { label: "To", value: "client@example.com" },
      { label: "Subject", summary: true, value: "Project update" },
      { label: "Message", summary: false, value: "A long message body" },
    ])
  })

  it("renders a sent message as a complete email receipt", () => {
    const rendered = gmailSendPresenter.render(
      props({
        id: "send-1",
        kind: "result",
        name: "gmail_send_message",
        status: "completed",
        args: {
          to: ["client@example.com"],
          subject: "Project update",
          body_text: "The work is complete.\nThanks,\nAda",
          cc: ["team@example.com"],
          bcc: [],
        },
        result: {
          results: [entry({ message_id: "message-1" })],
        },
      })
    )
    const html = render(rendered)

    expect(html).toContain('aria-label="Sent Gmail messages"')
    expect(html).toContain('aria-label="Sent email"')
    expect(html).toContain("Email sent")
    expect(html).toContain("Project update")
    expect(html).toContain("client@example.com")
    expect(html).toContain("team@example.com")
    expect(html).toContain("The work is complete.")
    expect(html).not.toContain("Result")
  })

  it("renders a clear unsent receipt when a run ends without a tool result", () => {
    const html = render(
      gmailSendPresenter.render(
        props({
          id: "send-1",
          kind: "call",
          name: "gmail_send_message",
          status: "failed",
          args: {
            to: ["client@example.com"],
            subject: "Project update",
            body_text: "The work is complete.",
          },
        })
      )
    )

    expect(html).toContain('aria-label="Unsent Gmail message"')
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain("Collapse results")
    expect(html).toContain("Send Gmail Message")
    expect(html).toContain("Email not sent")
    expect(html).toContain("Failed")
    expect(html).toContain("Details")
    expect(html).toContain("No delivery was confirmed.")
    expect(html).toContain("Project update")
    expect(html).toContain("client@example.com")
  })

  it("keeps malformed successful results in custom Gmail UI", () => {
    const html = render(
      gmailSendPresenter.render(
        props({
          id: "send-1",
          kind: "result",
          name: "gmail_send_message",
          status: "completed",
          result: {
            results: [
              entry({ message_id: "message-1" }),
              entry(null, { connection_id: "connection-2" }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Email not sent")
    expect(html).toContain("could not confirm")
  })

  it("replaces the pending skeleton with rich results before the streamed reply", () => {
    const called = agentStreamReducer(initialAgentStreamState, {
      type: "event",
      event: {
        event: "tool.call",
        data: {
          conversation_id: "conversation-1",
          run_id: "run-1",
          seq: 1,
          tool_call_id: "search-1",
          name: "gmail_search_messages",
          args: { query: "from:ada@example.com" },
        },
      },
    })
    const completed = agentStreamReducer(called, {
      type: "event",
      event: {
        event: "tool.result",
        data: {
          conversation_id: "conversation-1",
          run_id: "run-1",
          seq: 2,
          tool_call_id: "search-1",
          name: "gmail_search_messages",
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
            ],
          },
        },
      },
    })
    const withReply = agentStreamReducer(completed, {
      type: "event",
      event: {
        event: "message.delta",
        data: {
          conversation_id: "conversation-1",
          run_id: "run-1",
          seq: 3,
          message_id: "reply-1",
          text: "I found the requested messages.",
        },
      },
    })
    const toolCall = withReply.toolCalls["search-1"]
    expect(toolCall?.status).toBe("completed")
    expect(withReply.messages[0]?.text).toBe("I found the requested messages.")
    const html = render(
      gmailSearchPresenter.render(
        props({
          id: toolCall?.tool_call_id ?? "missing",
          kind: "result",
          name: toolCall?.name ?? "missing",
          status: toolCall?.status ?? "unknown",
          args: toolCall?.args,
          result: toolCall?.result,
        })
      )
    )
    expect(html).toContain("Quarterly update")
    expect(html).not.toContain("Searching mailboxes…")
    expect(html).not.toContain('aria-busy="true"')
  })

  it("keeps the rich presenter after persisted call/result pairing", () => {
    const result = {
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
      ],
    }
    const parsed = parseConversationMessages([
      persistedMessage("assistant-call", "assistant", 1, [
        {
          part_kind: "tool-call",
          tool_call_id: "search-1",
          tool_name: "gmail_search_messages",
          args: { query: "from:ada@example.com" },
        },
      ]),
      persistedMessage("tool-result", "tool", 2, [
        {
          part_kind: "tool-return",
          tool_call_id: "search-1",
          tool_name: "gmail_search_messages",
          outcome: "success",
          content: result,
        },
      ]),
      persistedMessage("assistant-reply", "assistant", 3, [
        { part_kind: "text", content: "I found the requested messages." },
      ]),
    ])
    const activity = parsed[0]?.toolActivities[0]
    expect(activity).toMatchObject({ status: "completed", result })
    expect(parsed[1]?.text).toEqual(["I found the requested messages."])
    expect(render(gmailSearchPresenter.render(props(activity ?? missingActivity())))).toContain(
      "Quarterly update"
    )
  })

  it("registers all Gmail presenters through the lazy integration module", async () => {
    await loadIntegrationUiModules(["gmail"])
    expect(integrationToolRowPresenters("gmail").map((presenter) => presenter.key)).toEqual([
      "gmail-search-messages",
      "gmail-read-message",
      "gmail-send-message",
    ])
  })

  it("resolves provider keys from tool-name prefixes without the presentations query", () => {
    expect(providerKeyForToolName("gmail_read_message")).toBe("gmail")
    expect(providerKeyForToolName("google_ads_run_report")).toBe("google_ads")
    expect(providerKeyForToolName("airtable_list_records")).toBe("airtable")
    expect(providerKeyForToolName("web_search")).toBeNull()
    expect(providerKeyForToolName("gmailish_tool")).toBeNull()
  })
})

function props(
  activity: ToolActivity,
  approvalDecision?: Parameters<typeof gmailSendPresenter.render>[0]["approvalDecision"]
) {
  return {
    activity,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "gmail",
  }
}

function entry(
  data: unknown,
  overrides: Partial<{
    connection_id: string
    display_name: string
    error_message: string | null
    external_id: string
    status: string
  }> = {}
) {
  return {
    connection_id: "connection-1",
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

function persistedMessage(
  id: string,
  role: string,
  sequence: number,
  parts: Record<string, unknown>[]
): ConversationMessage {
  return {
    id,
    conversation_id: "conversation-1",
    role,
    parts: { parts },
    metadata: null,
    tool_name: role === "tool" ? "gmail_search_messages" : null,
    error: null,
    sequence,
    client_message_id: null,
    created_at: "2026-07-22T09:00:00Z",
    updated_at: "2026-07-22T09:00:00Z",
  }
}

function missingActivity(): ToolActivity {
  return { id: "missing", kind: "unknown", status: "unknown", name: "missing" }
}
