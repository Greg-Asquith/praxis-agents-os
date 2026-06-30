import type { QueryClient } from "@tanstack/react-query"
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router"

import { getOptionalCurrentUser } from "@/features/auth/api/get-current-user"
import { LoginRoute } from "@/features/auth/routes/login-route"
import { ProfileRoute } from "@/features/auth/routes/profile-route"
import { RegisterRoute } from "@/features/auth/routes/register-route"
import { workspacesQueryOptions } from "@/features/workspaces/api/list-workspaces"
import { WorkspaceSettingsRoute } from "@/features/workspaces/routes/workspace-settings-route"
import { WorkspacesRoute } from "@/features/workspaces/routes/workspaces-route"
import { AppLayoutRoute } from "@/routes/app-layout"
import { AuthLayoutRoute } from "@/routes/auth-layout"
import { ErrorRoute } from "@/routes/error-route"
import { HomeRoute } from "@/routes/home"
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
  component: AuthLayoutRoute,
})

const loginRoute = createRoute({
  getParentRoute: () => authRoute,
  path: "/login",
  component: LoginRoute,
})

const registerRoute = createRoute({
  getParentRoute: () => authRoute,
  path: "/register",
  component: RegisterRoute,
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
  component: AppLayoutRoute,
})

const homeRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/",
  component: HomeRoute,
})

const workspacesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/workspaces",
  component: WorkspacesRoute,
})

const workspaceSettingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/workspace-settings",
  component: WorkspaceSettingsRoute,
})

const profileRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/profile",
  component: ProfileRoute,
})

const routeTree = rootRoute.addChildren([
  authRoute.addChildren([loginRoute, registerRoute]),
  appRoute.addChildren([homeRoute, workspacesRoute, workspaceSettingsRoute, profileRoute]),
])

export function createAppRouter(queryClient: QueryClient) {
  return createRouter({
    context: { queryClient },
    defaultPreload: "intent",
    routeTree,
  })
}
