// apps/web/tests/features/conversations/components/delegation-tool-row.test.ts

import { createElement, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterContextProvider,
} from "@tanstack/react-router"
import { describe, expect, it } from "vitest"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import { AssistantTurnContext } from "@/features/conversations/assistant-turn-context"
import { DelegationToolRow } from "@/features/conversations/components/delegation-tool-row"
import { ToolCallRowRendererContext } from "@/features/conversations/components/tool-call-row-renderer"
import type { DelegationToolActivity, ToolActivity } from "@/features/conversations/message-parts"
import type { ConversationMessagesResponse } from "@/features/conversations/types"

const CHILD_CONVERSATION_ID = "11111111-1111-4111-8111-111111111111"

describe("DelegationToolRow", () => {
  it("stays collapsed by default once the delegation has finished", () => {
    const html = renderWithProviders(
      createElement(DelegationToolRow, {
        activity: activity({ delegate: delegate({ output: "Done." }) }),
        defaultOpen: false,
      })
    )

    expect(html).toContain("Asked: Explain what you can do")
    expect(html).toContain(">Done<")
    expect(html).not.toContain("whitespace-pre-wrap")
  })

  it("renders a finished delegation as an exchange between the two agents", () => {
    const html = render(
      activity({
        delegate: delegate({
          conversationId: "11111111-1111-4111-8111-111111111111",
          output: "## What I can do\n\nI can draft replies.",
        }),
      })
    )

    expect(html).toContain("Conversation with Gmail Agent")
    expect(html).toContain("Asked: Explain what you can do")
    expect(html).toContain(">Assistant<")
    expect(html).toContain("Explain what you can do")
    expect(html).toContain(">Gmail Agent<")
    expect(html).toContain("What I can do")
    expect(html).toContain("I can draft replies.")
    expect(html).toContain(">Done<")
    expect(html).toContain("Open Full Conversation")
    expect(html).not.toContain(">Task<")
    expect(html).not.toContain(">Result<")
  })

  it("shows the delegate replying while the child run is still working", () => {
    const html = render(activity({ delegate: delegate({ status: "running" }), status: "running" }))

    expect(html).toContain("Conversation with Gmail Agent")
    expect(html).toContain(">Assistant<")
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain("Waiting for Gmail Agent to reply")
    expect(html).toContain(">Running<")
  })

  it("explains that the delegate is waiting on an approval", () => {
    const html = render(
      activity({
        delegate: delegate({ pendingApprovalCount: 1, status: "awaiting_approval" }),
        status: "awaiting_approval",
      })
    )

    expect(html).toContain("Gmail Agent needs your approval before it can continue.")
    expect(html).toContain("Approvals: 1 pending")
    expect(html).toContain(">Waiting<")
  })

  it("reports failures and declines in the reply position", () => {
    const failed = render(
      activity({
        delegate: delegate({ error: "The child run timed out.", status: "failed" }),
        status: "failed",
      })
    )
    const denied = render(
      activity({ decisionReason: "Not now.", delegate: delegate(), status: "denied" })
    )

    expect(failed).toContain("The child run timed out.")
    expect(failed).toContain(">Failed<")
    expect(denied).toContain("This delegation was declined, so no work was started.")
    expect(denied).toContain("Not now.")
    expect(denied).toContain(">Declined<")
  })

  it("lists the tool calls the delegate made in its own conversation", () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData<ConversationMessagesResponse>(
      conversationsQueryKeys.messages(CHILD_CONVERSATION_ID),
      {
        messages: [
          {
            id: "m-1",
            conversation_id: CHILD_CONVERSATION_ID,
            role: "assistant",
            parts: {
              parts: [
                {
                  part_kind: "tool-call",
                  tool_call_id: "call-1",
                  tool_name: "search_gmail",
                  args: {},
                },
              ],
            },
            metadata: { agent_run_id: "child-run" },
            tool_name: null,
            error: null,
            sequence: 1,
            client_message_id: null,
            created_at: "2026-09-08T20:47:00.000Z",
            updated_at: "2026-09-08T20:47:00.000Z",
          },
        ],
        total: 1,
      }
    )
    const html = renderWithProviders(
      createElement(
        ToolCallRowRendererContext,
        {
          value: ({ activity, compact }) =>
            createElement("div", { "data-child-row": String(compact) }, activity.name),
        },
        createElement(DelegationToolRow, {
          activity: activity({
            delegate: delegate({ conversationId: CHILD_CONVERSATION_ID, output: "Done." }),
          }),
          defaultOpen: true,
        })
      ),
      queryClient
    )

    expect(html).toContain('data-child-row="true">search_gmail<')
    expect(html.indexOf("search_gmail")).toBeLessThan(html.indexOf("Done."))
  })

  it("falls back to a generic asker label outside an assistant turn", () => {
    const html = render(activity({ delegate: delegate({ output: "Done." }) }), null)

    expect(html).toContain(">Agent<")
    expect(html).not.toContain(">Assistant<")
  })
})

function render(
  toolActivity: ToolActivity,
  caller: { agentId: string; label: string; metadata: null } | null = {
    agentId: "22222222-2222-4222-8222-222222222222",
    label: "Assistant",
    metadata: null,
  }
) {
  const row = createElement(DelegationToolRow, { activity: toolActivity, defaultOpen: true })
  return renderWithProviders(
    caller ? createElement(AssistantTurnContext, { value: caller }, row) : row
  )
}

function renderWithProviders(element: ReactElement, queryClient = new QueryClient()) {
  const rootRoute = createRootRoute()
  const router = createRouter({
    history: createMemoryHistory({ initialEntries: ["/"] }),
    routeTree: rootRoute.addChildren([
      createRoute({ getParentRoute: () => rootRoute, path: "/conversations/$conversationId" }),
    ]),
  })

  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(RouterContextProvider, { children: element, router })
    )
  )
}

function activity(overrides: Partial<ToolActivity>): ToolActivity {
  return {
    id: "call-1",
    kind: "call",
    name: "delegate_to_agent",
    status: "completed",
    ...overrides,
  }
}

function delegate(overrides: Partial<DelegationToolActivity> = {}): DelegationToolActivity {
  return {
    agentId: "33333333-3333-4333-8333-333333333333",
    agentName: "Gmail Agent",
    conversationId: null,
    error: null,
    output: null,
    pendingApprovalCount: 0,
    runId: null,
    status: "completed",
    taskPreview: "Explain what you can do",
    truncated: false,
    ...overrides,
  }
}
