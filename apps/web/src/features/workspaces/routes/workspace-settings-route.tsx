// apps/web/src/features/workspaces/routes/workspace-settings-route.tsx

import { PageHeader } from "@/components/shell/page-header"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { AuditSettingsPanel } from "@/features/audit/components/audit-settings-panel"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { InvitationsTable } from "@/features/workspaces/components/invitations-table"
import { MembersTable } from "@/features/workspaces/components/members-table"
import { WorkspaceSettingsForm } from "@/features/workspaces/components/workspace-settings-form"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"

export function WorkspaceSettingsRoute() {
  const { workspace } = useActiveWorkspace()
  const canManageWorkspace =
    workspace.current_user_role === "owner" || workspace.current_user_role === "admin"

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={<WorkspaceRoleBadge role={workspace.current_user_role} />}
        description="Manage workspace details, members, invitations, and audit history."
        title="Workspace settings"
      />

      <Tabs defaultValue="details">
        <TabsList variant="line">
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
          {canManageWorkspace ? <TabsTrigger value="invitations">Invitations</TabsTrigger> : null}
          {canManageWorkspace ? <TabsTrigger value="audit">Audit Log</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="details">
          <WorkspaceSettingsForm />
        </TabsContent>
        <TabsContent value="members">
          <MembersTable />
        </TabsContent>
        {canManageWorkspace ? (
          <TabsContent value="invitations">
            <InvitationsTable />
          </TabsContent>
        ) : null}
        {canManageWorkspace ? (
          <TabsContent value="audit">
            <AuditSettingsPanel />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  )
}
