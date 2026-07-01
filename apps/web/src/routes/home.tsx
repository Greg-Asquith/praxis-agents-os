// apps/web/src/routes/home.tsx

import { Link } from "@tanstack/react-router"
import {
  BlocksIcon,
  CalendarClockIcon,
  MessageSquarePlusIcon,
  MessagesSquareIcon,
  ShieldCheckIcon,
} from "lucide-react"
import { useSuspenseQuery } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"
import { formatDateTime } from "@/lib/format"

export function HomeRoute() {
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const { workspace, workspaces } = useActiveWorkspace()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <p className="text-muted-foreground text-sm font-medium">{workspace.name}</p>
        <h1 className="font-heading text-2xl font-semibold tracking-normal">Overview</h1>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Active workspace</CardTitle>
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
              Open settings
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Workspaces</CardTitle>
            <CardDescription>{workspaces.length} available</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-muted-foreground text-sm">
              Switch between personal and shared workspaces from the sidebar.
            </p>
            <Button variant="outline" size="sm" render={<Link to="/workspaces" />}>
              Manage workspaces
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Account</CardTitle>
            <CardDescription>{user.email}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-muted-foreground text-sm">
              Signed in as {user.display_name ?? user.email}.
            </p>
            <Separator />
            <p className="text-muted-foreground text-xs">
              Session controls and two-step verification will live with account settings.
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-4">
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MessagesSquareIcon className="size-4" />
              Conversations
            </CardTitle>
            <CardDescription>Talk to active agents in a workspace thread.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button size="sm" render={<Link to="/conversations/new" />}>
              <MessageSquarePlusIcon data-icon="inline-start" />
              New conversation
            </Button>
            <Button variant="outline" size="sm" render={<Link to="/conversations" />}>
              Open list
            </Button>
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BlocksIcon className="size-4" />
              Agents
            </CardTitle>
            <CardDescription>Configure models, tools, delegation, and approvals.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" size="sm" render={<Link to="/agents" />}>
              Manage agents
            </Button>
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CalendarClockIcon className="size-4" />
              Schedules
            </CardTitle>
            <CardDescription>Schedule management is not available yet.</CardDescription>
          </CardHeader>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheckIcon className="size-4" />
              Approvals
            </CardTitle>
            <CardDescription>
              Approval decisions appear inside waiting conversations.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    </div>
  )
}
