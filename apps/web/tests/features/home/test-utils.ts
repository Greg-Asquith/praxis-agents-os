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

export function renderHomeComponent(
  element: ReactElement,
  queryClient = new QueryClient()
): string {
  const rootRoute = createRootRoute()
  const routes = [
    createRoute({ getParentRoute: () => rootRoute, path: "/agents" }),
    createRoute({ getParentRoute: () => rootRoute, path: "/conversations" }),
    createRoute({ getParentRoute: () => rootRoute, path: "/conversations/new" }),
    createRoute({
      getParentRoute: () => rootRoute,
      path: "/conversations/$conversationId",
    }),
    createRoute({ getParentRoute: () => rootRoute, path: "/schedules" }),
    createRoute({
      getParentRoute: () => rootRoute,
      path: "/schedules/$scheduleId",
    }),
  ]
  const router = createRouter({
    history: createMemoryHistory({ initialEntries: ["/"] }),
    routeTree: rootRoute.addChildren(routes),
  })

  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(RouterContextProvider, { children: element, router })
    )
  )
}
