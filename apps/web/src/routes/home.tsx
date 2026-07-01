// apps/web/src/routes/home.tsx

import { useMemo, type ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import { useSuspenseQueries } from "@tanstack/react-query"
import {
  BotIcon,
  CircleIcon,
  InboxIcon,
  MessageSquarePlusIcon,
  MessageSquareTextIcon,
  Settings2Icon,
  ShieldAlertIcon,
  StarsIcon,
  UserCircleIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { Separator } from "@/components/ui/separator"
import { countActiveAgents, countApprovalGatedAgents } from "@/features/agents/agent-metrics"
import { agentsQueryOptions } from "@/features/agents/api/list-agents"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { conversationsQueryOptions } from "@/features/conversations/api/list-conversations"
import { ConversationList } from "@/features/conversations/components/conversation-list"
import { sortConversations } from "@/features/conversations/sort"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"
import { formatDateTime, pluralize } from "@/lib/format"

const ATTENTION_LIMIT = 5
const RECENT_LIMIT = 6

export function HomeRoute() {
  const { workspace, workspaces } = useActiveWorkspace()
  const [userQuery, agentsQuery, conversationsQuery] = useSuspenseQueries({
    queries: [
      currentUserQueryOptions(),
      agentsQueryOptions({ includeInactive: true, limit: 100 }),
      conversationsQueryOptions({ limit: 10 }),
    ],
  })

  const user = userQuery.data
  const agents = agentsQuery.data.agents
  const conversations = useMemo(
    () => sortConversations(conversationsQuery.data.conversations),
    [conversationsQuery.data.conversations]
  )
  const attentionConversations = useMemo(
    () =>
      conversations.filter((conversation) => conversation.needs_approval || conversation.unread),
    [conversations]
  )
  const activeAgents = countActiveAgents(agents)
  const approvalGatedAgents = countApprovalGatedAgents(agents)
  const conversationsNeedingApproval = conversations.filter(
    (conversation) => conversation.needs_approval
  ).length
  const unreadConversations = conversations.filter((conversation) => conversation.unread).length

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-col gap-2">
          <p className="text-muted-foreground text-sm font-medium">{workspace.name}</p>
          <div>
            <h1 className="font-heading text-2xl font-semibold tracking-normal">
              Operations dashboard
            </h1>
            <p className="text-muted-foreground mt-1 max-w-2xl text-sm">
              Live agent state, approvals, and recent workspace conversations.
            </p>
          </div>
        </div>
        <Button render={<Link to="/conversations/new" />}>
          <MessageSquarePlusIcon data-icon="inline-start" />
          New Conversation
        </Button>
      </div>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryTile
          description="Blocked until decisions are submitted"
          icon={<ShieldAlertIcon className="size-4" />}
          label="Needs approval"
          value={conversationsNeedingApproval}
        />
        <SummaryTile
          description="Conversations marked unread"
          icon={<CircleIcon className="size-4 fill-current" />}
          label="Unread conversations"
          value={unreadConversations}
        />
        <SummaryTile
          description="Ready for new turns"
          icon={<BotIcon className="size-4" />}
          label="Active agents"
          value={activeAgents}
        />
        <SummaryTile
          description="Active agents with human review"
          icon={<StarsIcon className="size-4" />}
          label="Approval-gated agents"
          value={approvalGatedAgents}
        />
      </section>

      <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <DashboardPanel
          description={`${String(attentionConversations.length)} ${pluralize(
            attentionConversations.length,
            "conversation"
          )} unread or awaiting approval`}
          title="Needs attention"
        >
          <ConversationList
            conversations={attentionConversations.slice(0, ATTENTION_LIMIT)}
            emptyState={
              <EmptyState
                action={
                  <Button variant="outline" render={<Link to="/conversations" />}>
                    Open Conversations
                  </Button>
                }
                description="No unread or approval-gated conversations right now."
                className="border-none"
                icon={<InboxIcon className="size-5" />}
                size="compact"
                title="Nothing pending"
              />
            }
            showRunStatus
            sourceVisibility="none"
          />
        </DashboardPanel>

        <DashboardPanel
          action={
            <Button variant="outline" render={<Link to="/conversations" />}>
              View All
            </Button>
          }
          description={`${String(conversationsQuery.data.total)} ${pluralize(
            conversationsQuery.data.total,
            "conversation"
          )} in this workspace`}
          title="Recent conversations"
        >
          <ConversationList
            conversations={conversations.slice(0, RECENT_LIMIT)}
            emptyState={
              <EmptyState
                action={
                  <Button render={<Link to="/conversations/new" />}>
                    <MessageSquarePlusIcon data-icon="inline-start" />
                    New Conversation
                  </Button>
                }
                description="Start a blank chat and choose an active agent."
                className="border-none"
                icon={<MessageSquareTextIcon className="size-5" />}
                size="compact"
                title="No conversations yet"
              />
            }
            showRunStatus
            sourceVisibility="always"
          />
        </DashboardPanel>
      </section>

      <section className="grid gap-4 lg:grid-cols-4">
        <Card size="sm">
          <CardHeader>
            <CardTitle>Workspace</CardTitle>
            <CardDescription>{workspace.slug}</CardDescription>
            <CardAction>
              <WorkspaceRoleBadge role={workspace.current_user_role} />
            </CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-muted-foreground text-sm">
              Created {formatDateTime(workspace.created_at)}
            </p>
            <Button variant="outline" size="sm" render={<Link to="/workspace-settings" />}>
              <Settings2Icon data-icon="inline-start" />
              Workspace settings
            </Button>
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle>Workspaces</CardTitle>
            <CardDescription>
              {workspaces.length} {pluralize(workspaces.length, "workspace")} available
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-muted-foreground text-sm">Current workspace: {workspace.name}</p>
            <Button variant="outline" size="sm" render={<Link to="/workspaces" />}>
              Manage workspaces
            </Button>
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle>Agents</CardTitle>
            <CardDescription>
              {agentsQuery.data.total} {pluralize(agentsQuery.data.total, "agent")} configured
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-muted-foreground text-sm">
              {activeAgents} {pluralize(activeAgents, "agent")} currently active
            </p>
            <Button variant="outline" size="sm" render={<Link to="/agents" />}>
              <BotIcon data-icon="inline-start" />
              Manage agents
            </Button>
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle>Account</CardTitle>
            <CardDescription>{user.email}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-muted-foreground text-sm">
              Signed in as {user.display_name ?? user.email}.
            </p>
            <Separator />
            <Button variant="outline" size="sm" render={<Link to="/profile" />}>
              <UserCircleIcon data-icon="inline-start" />
              Profile settings
            </Button>
          </CardContent>
        </Card>
      </section>
    </div>
  )
}

function SummaryTile({
  description,
  icon,
  label,
  value,
}: {
  description: string
  icon: ReactNode
  label: string
  value: number
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-sm">{label}</CardTitle>
        <CardAction>
          <div className="bg-muted text-muted-foreground flex size-8 items-center justify-center rounded-lg">
            {icon}
          </div>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        <p className="font-heading text-3xl font-semibold tabular-nums">{value}</p>
        <p className="text-muted-foreground text-xs">{description}</p>
      </CardContent>
    </Card>
  )
}

function DashboardPanel({
  action,
  children,
  description,
  title,
}: {
  action?: ReactNode
  children: ReactNode
  description: string
  title: string
}) {
  return (
    <section className="bg-background flex min-w-0 flex-col rounded-xl border">
      <div className="flex flex-col justify-between gap-3 p-4 md:flex-row md:items-center">
        <div className="min-w-0">
          <h2 className="font-heading text-base font-medium">{title}</h2>
          <p className="text-muted-foreground mt-1 text-sm">{description}</p>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <Separator />
      <div className="p-2 md:p-3">{children}</div>
    </section>
  )
}
