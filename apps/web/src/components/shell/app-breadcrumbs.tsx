// apps/web/src/components/shell/app-breadcrumbs.tsx

import { Link } from "@tanstack/react-router"
import { queryOptions, useQuery } from "@tanstack/react-query"
import { ChevronRightIcon } from "lucide-react"

import { getAgent } from "@/features/agents/api/get-agent"
import { agentsQueryKeys } from "@/features/agents/api/list-agents"
import type { Conversation } from "@/features/conversations/types"
import { cn } from "@/lib/utils"

type BreadcrumbRoute = "/" | "/agents" | "/conversations" | "/workspaces" | "/workspace-settings"

type BreadcrumbItem = {
  key: string
  label: string
  to?: BreadcrumbRoute
}

type AppBreadcrumbsProps = {
  conversations: Conversation[]
  pathname: string
}

const DISABLED_AGENT_BREADCRUMB_QUERY_KEY = ["agents", "breadcrumb", "disabled"] as const

export function AppBreadcrumbs({ conversations, pathname }: AppBreadcrumbsProps) {
  const agentId = getEntityId(pathname, "agents")
  const agentQuery = useQuery({
    ...agentBreadcrumbQueryOptions(agentId),
    enabled: agentId !== null,
  })

  const conversationId = getEntityId(pathname, "conversations")
  const conversation = conversationId
    ? conversations.find((item) => item.id === conversationId)
    : null
  const breadcrumbs = getBreadcrumbs({
    agentName: agentQuery.data?.name ?? null,
    conversationTitle: conversation ? (conversation.title ?? "Untitled conversation") : null,
    pathname,
  })
  const currentLabel = breadcrumbs.at(-1)?.label ?? "Home"

  return (
    <>
      <p className="min-w-0 truncate text-sm font-medium md:hidden">{currentLabel}</p>
      <nav className="hidden min-w-0 md:block" aria-label="Breadcrumb">
        <ol className="flex min-w-0 items-center gap-1 text-sm">
          {breadcrumbs.map((item, index) => {
            const isLast = index === breadcrumbs.length - 1

            return (
              <li key={item.key} className="flex min-w-0 items-center gap-1">
                {index > 0 && (
                  <ChevronRightIcon
                    className="text-muted-foreground size-3.5 shrink-0"
                    aria-hidden="true"
                  />
                )}
                {item.to && !isLast ? (
                  <Link
                    to={item.to}
                    className="text-muted-foreground hover:text-foreground truncate transition-colors"
                  >
                    {item.label}
                  </Link>
                ) : (
                  <span
                    aria-current={isLast ? "page" : undefined}
                    className={cn(
                      "truncate",
                      isLast ? "text-foreground font-medium" : "text-muted-foreground"
                    )}
                  >
                    {item.label}
                  </span>
                )}
              </li>
            )
          })}
        </ol>
      </nav>
    </>
  )
}

function getBreadcrumbs({
  agentName,
  conversationTitle,
  pathname,
}: {
  agentName: string | null
  conversationTitle: string | null
  pathname: string
}): BreadcrumbItem[] {
  const segments = getPathSegments(pathname)
  const [section, detail] = segments

  if (!section) {
    return [{ key: "home", label: "Home" }]
  }

  if (section === "agents") {
    if (detail === "new") {
      return [
        { key: "agents", label: "Agents", to: "/agents" },
        { key: "agents-new", label: "New agent" },
      ]
    }

    return detail
      ? [
          { key: "agents", label: "Agents", to: "/agents" },
          { key: "agents-detail", label: agentName ?? "Agent" },
        ]
      : [{ key: "agents", label: "Agents" }]
  }

  if (section === "conversations") {
    if (detail === "new") {
      return [
        { key: "conversations", label: "Conversations", to: "/conversations" },
        { key: "conversations-new", label: "New Conversation" },
      ]
    }

    return detail
      ? [
          { key: "conversations", label: "Conversations", to: "/conversations" },
          { key: "conversations-detail", label: conversationTitle ?? "Conversation" },
        ]
      : [{ key: "conversations", label: "Conversations" }]
  }

  if (section === "workspaces") {
    return [{ key: "workspaces", label: "Workspaces" }]
  }

  if (section === "workspace-settings") {
    return [{ key: "settings", label: "Settings" }]
  }

  if (section === "profile") {
    return [{ key: "profile", label: "Profile settings" }]
  }

  return [
    { key: "home", label: "Home", to: "/" },
    { key: `route-${section}`, label: titleFromSegment(section) },
  ]
}

function agentBreadcrumbQueryOptions(agentId: string | null) {
  return queryOptions({
    queryFn: () => getAgent(agentId ?? ""),
    queryKey: agentId ? agentsQueryKeys.detail(agentId) : DISABLED_AGENT_BREADCRUMB_QUERY_KEY,
    staleTime: 30_000,
  })
}

function getEntityId(pathname: string, section: "agents" | "conversations") {
  const segments = getPathSegments(pathname)
  if (segments[0] !== section || !segments[1] || segments[1] === "new") {
    return null
  }

  return segments[1]
}

function getPathSegments(pathname: string) {
  return pathname
    .split("/")
    .filter(Boolean)
    .map((segment) => decodeURIComponent(segment))
}

function titleFromSegment(segment: string) {
  return segment
    .split("-")
    .filter(Boolean)
    .map((part) => `${part[0]?.toUpperCase() ?? ""}${part.slice(1)}`)
    .join(" ")
}
