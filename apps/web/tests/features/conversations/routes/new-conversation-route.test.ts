import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, expect, it, vi } from "vitest"

import { NewConversationRoute } from "@/features/conversations/routes/new-conversation-route"

const state = vi.hoisted(
  (): {
    file: string | undefined
    pending: boolean
    error: boolean
    published: boolean
    failAfterLoaded: boolean
    queryEnabled: boolean[]
    composerProps: Record<string, unknown>
    personal: boolean
    sharedByDefault: boolean
  } => ({
    file: "file-1",
    pending: false,
    error: false,
    published: true,
    failAfterLoaded: false,
    queryEnabled: [],
    composerProps: {},
    personal: false,
    sharedByDefault: false,
  })
)
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({
    workspace: {
      name: "Example team",
      is_personal: state.personal,
      conversations_shared_by_default: state.sharedByDefault,
    },
  }),
}))
vi.mock("@tanstack/react-router", () => ({
  useRouterState: () => ({ file: state.file }),
}))
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (value: unknown) => value,
  useQuery: ({ enabled }: { enabled: boolean }) => {
    state.queryEnabled.push(enabled)
    return {
      isFetchedAfterMount: !state.pending,
      isPending: state.pending,
      isError: state.error || (state.failAfterLoaded && !enabled),
      data: {
        id: "file-1",
        scope: "platform",
        is_published: state.published,
        category: "editable_text",
        name: "Policy.txt",
        content_type: "text/plain",
        size_bytes: 120,
      },
    }
  },
}))
vi.mock("@/features/agents/api/list-agents", () => ({
  useAgentsQuery: () => ({
    data: { agents: [{ id: "agent-1", name: "Assistant", is_active: true }] },
  }),
}))
vi.mock("@/features/models/api/list-model-catalog", () => ({
  useModelCatalogQuery: () => ({ data: {} }),
}))
vi.mock("@/features/conversations/conversation-workspace-context", () => ({
  useConversationWorkspace: () => ({ stream: { isStreaming: false } }),
}))
vi.mock("@/features/agents/components/agent-identity-icon", () => ({
  AgentIdentityIcon: () => null,
}))
vi.mock("@/features/conversations/components/conversation-composer", () => ({
  ConversationComposer: (props: Record<string, unknown>) => {
    state.composerProps = props
    return "Conversation composer"
  },
}))

beforeEach(() => {
  state.file = "file-1"
  state.pending = false
  state.error = false
  state.published = true
  state.failAfterLoaded = false
  state.queryEnabled = []
  state.composerProps = {}
  state.personal = false
  state.sharedByDefault = false
})

it("blocks inaccessible or withdrawn attachments", () => {
  state.error = true
  expect(renderToStaticMarkup(createElement(NewConversationRoute))).toContain(
    "File cannot be attached"
  )
  state.error = false
  state.published = false
  expect(renderToStaticMarkup(createElement(NewConversationRoute))).toContain(
    "File cannot be attached"
  )
  expect(state.composerProps).toEqual({})
})
