// apps/web/src/app/router.tsx

import type { QueryClient } from "@tanstack/react-query"
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Outlet,
  redirect,
} from "@tanstack/react-router"

import { getOptionalCurrentUser } from "@/features/auth/api/get-current-user"
import { OAUTH_LOGIN_CALLBACK_PATH } from "@/features/auth/oauth-login-constants"
import { workspacesQueryOptions } from "@/features/workspaces/api/list-workspaces"
import { ErrorRoute } from "@/routes/error-route"
import { NotFoundRoute } from "@/routes/not-found"
import { PendingRoute } from "@/routes/pending"

type RouterContext = {
  queryClient: QueryClient
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: () => <Outlet />,
  errorComponent: ({ error }) => <ErrorRoute error={error} />,
  notFoundComponent: NotFoundRoute,
  pendingComponent: PendingRoute,
})

const authRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "auth",
  beforeLoad: async ({ context }) => {
    const user = await getOptionalCurrentUser(context.queryClient)
    if (user) {
      throw redirect({ to: "/" })
    }
  },
  component: lazyRouteComponent(() => import("@/routes/auth-layout"), "AuthLayoutRoute"),
})

const loginRoute = createRoute({
  getParentRoute: () => authRoute,
  path: "/login",
  component: lazyRouteComponent(() => import("@/features/auth/routes/login-route"), "LoginRoute"),
})

const registerRoute = createRoute({
  getParentRoute: () => authRoute,
  path: "/register",
  component: lazyRouteComponent(
    () => import("@/features/auth/routes/register-route"),
    "RegisterRoute"
  ),
})

const oauthLoginCallbackRoute = createRoute({
  getParentRoute: () => authRoute,
  path: OAUTH_LOGIN_CALLBACK_PATH,
  component: lazyRouteComponent(
    () => import("@/features/auth/routes/oauth-login-callback-route"),
    "OAuthLoginCallbackRoute"
  ),
})

const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  beforeLoad: async ({ context }) => {
    const user = await getOptionalCurrentUser(context.queryClient)
    if (!user) {
      throw redirect({ to: "/login" })
    }

    await context.queryClient.ensureQueryData(workspacesQueryOptions())
  },
  component: lazyRouteComponent(() => import("@/routes/app-layout"), "AppLayoutRoute"),
})

const homeRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/",
  component: lazyRouteComponent(() => import("@/routes/home"), "HomeRoute"),
})

const workspacesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/workspaces",
  component: lazyRouteComponent(
    () => import("@/features/workspaces/routes/workspaces-route"),
    "WorkspacesRoute"
  ),
})

const conversationsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/conversations",
  component: lazyRouteComponent(
    () => import("@/features/conversations/routes/conversations-route"),
    "ConversationsRoute"
  ),
})

const conversationRuntimeRoute = createRoute({
  getParentRoute: () => appRoute,
  id: "conversation-runtime",
  component: lazyRouteComponent(
    () => import("@/features/conversations/routes/conversation-runtime-route"),
    "ConversationRuntimeRoute"
  ),
})

const newConversationRoute = createRoute({
  getParentRoute: () => conversationRuntimeRoute,
  path: "/conversations/new",
  component: lazyRouteComponent(
    () => import("@/features/conversations/routes/new-conversation-route"),
    "NewConversationRoute"
  ),
})

const conversationRoute = createRoute({
  getParentRoute: () => conversationRuntimeRoute,
  path: "/conversations/$conversationId",
  component: lazyRouteComponent(
    () => import("@/features/conversations/routes/conversation-route"),
    "ConversationRoute"
  ),
})

const agentsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/agents",
  component: lazyRouteComponent(
    () => import("@/features/agents/routes/agents-route"),
    "AgentsRoute"
  ),
})

const newAgentRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/agents/new",
  component: lazyRouteComponent(
    () => import("@/features/agents/routes/new-agent-route"),
    "NewAgentRoute"
  ),
})

const agentDetailRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/agents/$agentId",
  component: lazyRouteComponent(
    () => import("@/features/agents/routes/agent-detail-route"),
    "AgentDetailRoute"
  ),
})

const skillsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/skills",
  component: lazyRouteComponent(
    () => import("@/features/skills/routes/skills-route"),
    "SkillsRoute"
  ),
})

const newSkillRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/skills/new",
  component: lazyRouteComponent(
    () => import("@/features/skills/routes/new-skill-route"),
    "NewSkillRoute"
  ),
})

const skillDetailRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/skills/$skillId",
  component: lazyRouteComponent(
    () => import("@/features/skills/routes/skill-detail-route"),
    "SkillDetailRoute"
  ),
})

const schedulesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/schedules",
  component: lazyRouteComponent(
    () => import("@/features/schedules/routes/schedules-route"),
    "SchedulesRoute"
  ),
})

const newScheduleRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/schedules/new",
  component: lazyRouteComponent(
    () => import("@/features/schedules/routes/new-schedule-route"),
    "NewScheduleRoute"
  ),
})

const scheduleDetailRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/schedules/$scheduleId",
  component: lazyRouteComponent(
    () => import("@/features/schedules/routes/schedule-detail-route"),
    "ScheduleDetailRoute"
  ),
})

const workspaceSettingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/workspace-settings",
  component: lazyRouteComponent(
    () => import("@/features/workspaces/routes/workspace-settings-route"),
    "WorkspaceSettingsRoute"
  ),
})

const profileRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/profile",
  component: lazyRouteComponent(
    () => import("@/features/auth/routes/profile-route"),
    "ProfileRoute"
  ),
})

const oauthLinkCallbackRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/oauth/link/callback",
  component: lazyRouteComponent(
    () => import("@/features/auth/routes/oauth-link-callback-route"),
    "OAuthLinkCallbackRoute"
  ),
})

const routeTree = rootRoute.addChildren([
  authRoute.addChildren([loginRoute, registerRoute, oauthLoginCallbackRoute]),
  appRoute.addChildren([
    homeRoute,
    conversationsRoute,
    conversationRuntimeRoute.addChildren([newConversationRoute, conversationRoute]),
    agentsRoute,
    newAgentRoute,
    agentDetailRoute,
    skillsRoute,
    newSkillRoute,
    skillDetailRoute,
    schedulesRoute,
    newScheduleRoute,
    scheduleDetailRoute,
    workspacesRoute,
    workspaceSettingsRoute,
    profileRoute,
    oauthLinkCallbackRoute,
  ]),
])

export function createAppRouter(queryClient: QueryClient) {
  return createRouter({
    context: { queryClient },
    defaultPreload: "intent",
    routeTree,
  })
}
