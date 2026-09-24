import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, expect, it, vi } from "vitest"

import { AppShell } from "@/components/shell/app-shell"

const state = vi.hoisted(() => ({
  personal: false,
  shared: false,
  query: vi.fn(),
  sidebar: vi.fn(),
  mobile: vi.fn(),
  breadcrumbs: vi.fn(),
  conversations: [{ id: "shared", access: "viewer" }],
}))
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
  useRouterState: () => ({ pathname: "/shared-chats/team/shared", search: {} }),
}))
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (options: unknown) => options,
  useSuspenseQuery: () => ({ data: {} }),
}))
vi.mock("@/features/auth/api/logout", () => ({ useLogoutMutation: () => ({ mutate: vi.fn() }) }))
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({
    workspace: {
      slug: "team",
      is_personal: state.personal,
      conversations_shared_by_default: state.shared,
    },
    workspaces: [],
    setWorkspaceBySlug: vi.fn(),
  }),
}))
vi.mock("@/features/conversations/api/list-conversations", () => ({
  useConversationsQuery: (params: unknown) => {
    state.query(params)
    return { data: { conversations: state.conversations } }
  },
}))
vi.mock("@/components/shell/sidebar-conversations", () => ({
  SidebarConversations: (props: unknown) => {
    state.sidebar(props)
    return null
  },
}))
vi.mock("@/components/shell/mobile-menu", () => ({
  MobileMenu: (props: unknown) => {
    state.mobile(props)
    return null
  },
}))
vi.mock("@/components/shell/app-breadcrumbs", () => ({
  AppBreadcrumbs: (props: unknown) => {
    state.breadcrumbs(props)
    return null
  },
}))
vi.mock("@/components/shell/primary-navigation", () => ({ PrimaryNavigation: () => null }))
vi.mock("@/components/shell/sidebar-footer", () => ({ SidebarFooter: () => null }))
vi.mock("@/components/shell/sidebar-header", () => ({ SidebarHeader: () => null }))
vi.mock("@/components/shell/workspace-switcher", () => ({ WorkspaceSwitcher: () => null }))

beforeEach(() => {
  vi.clearAllMocks()
})

it.each([
  [false, true, "all"],
  [false, false, "mine"],
  [true, true, "mine"],
  [true, false, "mine"],
])("selects scope for personal=%s, sharing=%s", (personal, shared, scope) => {
  state.personal = personal
  state.shared = shared
  renderToStaticMarkup(createElement(AppShell, { children: "Content" }))
  expect(state.query).toHaveBeenCalledWith({ limit: 50, scope })
  for (const surface of [state.sidebar, state.mobile, state.breadcrumbs]) {
    expect(surface).toHaveBeenCalledWith(
      expect.objectContaining({ conversations: state.conversations })
    )
  }
})
