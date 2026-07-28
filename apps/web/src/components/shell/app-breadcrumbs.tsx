// apps/web/src/components/shell/app-breadcrumbs.tsx

import { Link } from "@tanstack/react-router"
import { queryOptions, useQuery } from "@tanstack/react-query"
import { ChevronRightIcon } from "lucide-react"

import { getAgent } from "@/features/agents/api/get-agent"
import { agentsQueryKeys } from "@/features/agents/api/list-agents"
import type { Conversation } from "@/features/conversations/types"
import { integrationProvidersQueryOptions } from "@/features/integrations/api/list-providers"
import { getSchedule } from "@/features/schedules/api/get-schedule"
import { schedulesQueryKeys } from "@/features/schedules/api/list-schedules"
import { scheduleTitle } from "@/features/schedules/format"
import { titleFromSegment } from "@/lib/format"
import { cn } from "@/lib/utils"

type BreadcrumbRoute =
  | "/"
  | "/agents"
  | "/artifacts"
  | "/conversations"
  | "/context"
  | "/integrations"
  | "/knowledge"
  | "/schedules"
  | "/skills"
  | "/workspaces"
  | "/workspace-settings"

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
const DISABLED_SCHEDULE_BREADCRUMB_QUERY_KEY = ["schedules", "breadcrumb", "disabled"] as const

export function AppBreadcrumbs({ conversations, pathname }: AppBreadcrumbsProps) {
  const agentId = getEntityId(pathname, "agents")
  const agentQuery = useQuery({
    ...agentBreadcrumbQueryOptions(agentId),
    enabled: agentId !== null,
  })
  const scheduleId = getEntityId(pathname, "schedules")
  const scheduleQuery = useQuery({
    ...scheduleBreadcrumbQueryOptions(scheduleId),
    enabled: scheduleId !== null,
  })
  const integrationProviderKey = getIntegrationProviderKey(pathname)
  const integrationProvidersQuery = useQuery({
    ...integrationProvidersQueryOptions(),
    enabled: integrationProviderKey !== null,
  })

  const conversationId = getEntityId(pathname, "conversations")
  const conversation = conversationId
    ? conversations.find((item) => item.id === conversationId)
    : null
  const breadcrumbs = getBreadcrumbs({
    agentName: agentQuery.data?.name ?? null,
    conversationTitle: conversation ? (conversation.title ?? "Untitled conversation") : null,
    integrationProviderName:
      integrationProvidersQuery.data?.find(
        (provider) => provider.provider_key === integrationProviderKey
      )?.display_name ?? null,
    pathname,
    scheduleName: scheduleQuery.data ? scheduleTitle(scheduleQuery.data) : null,
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
  integrationProviderName,
  pathname,
  scheduleName,
}: {
  agentName: string | null
  conversationTitle: string | null
  integrationProviderName: string | null
  pathname: string
  scheduleName: string | null
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
        { key: "agents-new", label: "New Agent" },
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

  if (section === "context") {
    return [{ key: "context", label: "Context" }]
  }

  if (section === "skills") {
    if (detail === "new") {
      return [
        { key: "context", label: "Context", to: "/context" },
        { key: "skills", label: "Skills", to: "/skills" },
        { key: "skills-new", label: "New Skill" },
      ]
    }

    return detail
      ? [
          { key: "context", label: "Context", to: "/context" },
          { key: "skills", label: "Skills", to: "/skills" },
          { key: "skills-detail", label: "Skill" },
        ]
      : [
          { key: "context", label: "Context", to: "/context" },
          { key: "skills", label: "Skills" },
        ]
  }

  if (section === "knowledge") {
    return detail
      ? [
          { key: "context", label: "Context", to: "/context" },
          { key: "knowledge", label: "Knowledge Base", to: "/knowledge" },
          { key: "knowledge-detail", label: "Document" },
        ]
      : [
          { key: "context", label: "Context", to: "/context" },
          { key: "knowledge", label: "Knowledge Base" },
        ]
  }

  if (section === "memories") {
    return [
      { key: "context", label: "Context", to: "/context" },
      { key: "memory", label: "Memory" },
    ]
  }

  if (section === "files") {
    return [
      { key: "context", label: "Context", to: "/context" },
      { key: "files", label: "Files" },
    ]
  }

  if (section === "artifacts") {
    return detail
      ? [
          { key: "context", label: "Context", to: "/context" },
          { key: "artifacts", label: "Artifacts", to: "/artifacts" },
          { key: "artifacts-detail", label: "Artifact" },
        ]
      : [
          { key: "context", label: "Context", to: "/context" },
          { key: "artifacts", label: "Artifacts" },
        ]
  }

  if (section === "schedules") {
    if (detail === "new") {
      return [
        { key: "schedules", label: "Schedules", to: "/schedules" },
        { key: "schedules-new", label: "New Schedule" },
      ]
    }

    return detail
      ? [
          { key: "schedules", label: "Schedules", to: "/schedules" },
          { key: "schedules-detail", label: scheduleName ?? "Schedule" },
        ]
      : [{ key: "schedules", label: "Schedules" }]
  }

  if (section === "integrations") {
    if (detail === "context-groups") {
      return [
        { key: "context", label: "Context", to: "/context" },
        { key: "context-groups", label: "Context Groups" },
      ]
    }

    return detail && detail !== "oauth"
      ? [
          { key: "integrations", label: "Integrations", to: "/integrations" },
          {
            key: "integrations-detail",
            label: integrationProviderName ?? titleFromSegment(detail.replaceAll("_", "-")),
          },
        ]
      : [{ key: "integrations", label: "Integrations" }]
  }

  if (section === "workspaces") {
    return [{ key: "workspaces", label: "Workspaces" }]
  }

  if (section === "workspace-settings") {
    return [{ key: "settings", label: "Workspace Settings" }]
  }

  if (section === "profile") {
    return [{ key: "profile", label: "Profile Settings" }]
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

function scheduleBreadcrumbQueryOptions(scheduleId: string | null) {
  return queryOptions({
    queryFn: () => getSchedule(scheduleId ?? ""),
    queryKey: scheduleId
      ? schedulesQueryKeys.detail(scheduleId)
      : DISABLED_SCHEDULE_BREADCRUMB_QUERY_KEY,
    staleTime: 15_000,
  })
}

function getEntityId(pathname: string, section: "agents" | "conversations" | "schedules") {
  const segments = getPathSegments(pathname)
  if (segments[0] !== section || !segments[1] || segments[1] === "new") {
    return null
  }

  return segments[1]
}

function getIntegrationProviderKey(pathname: string) {
  const segments = getPathSegments(pathname)
  if (
    segments[0] !== "integrations" ||
    !segments[1] ||
    segments[1] === "context-groups" ||
    segments[1] === "oauth"
  ) {
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
