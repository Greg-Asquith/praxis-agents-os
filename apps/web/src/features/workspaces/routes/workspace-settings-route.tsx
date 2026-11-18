// apps/web/src/features/workspaces/routes/workspace-settings-route.tsx

import { PageHeader } from "@/components/shell/page-header"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { AuditSettingsPanel } from "@/features/audit/components/audit-settings-panel"
import { ClassifiersSettingsPanel } from "@/features/classifiers/components/classifiers-settings-panel"
import { DoNotEmailPanel } from "@/features/email-suppressions/components/do-not-email-panel"
import { ToolSettingsPanel } from "@/features/tools/components/tool-settings-panel"
import { UsageSettingsPanel } from "@/features/usage/components/usage-dashboard-panel"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { InvitationsTable } from "@/features/workspaces/components/invitations-table"
import { MembersTable } from "@/features/workspaces/components/members-table"
import { WorkspaceSettingsForm } from "@/features/workspaces/components/workspace-settings-form"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"
import { canEditWorkspace, canManageWorkspace } from "@/features/workspaces/permissions"

export function WorkspaceSettingsRoute() {
  const { workspace } = useActiveWorkspace()
  const canManage = canManageWorkspace(workspace.current_user_role)
  const canEdit = canEditWorkspace(workspace.current_user_role)

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={<WorkspaceRoleBadge role={workspace.current_user_role} />}
        description="Manage workspace details, members, tools, reusable classifiers, who agents can email, usage, and audit history."
        title="Workspace Settings"
      />

      <Tabs defaultValue="details">
        <TabsList
          className="max-w-full justify-start overflow-x-auto overflow-y-hidden"
          variant="line"
        >
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
          {canManage ? <TabsTrigger value="invitations">Invitations</TabsTrigger> : null}
          {canManage ? <TabsTrigger value="tools">Tools</TabsTrigger> : null}
          {canManage ? <TabsTrigger value="classifiers">Classifiers</TabsTrigger> : null}
          {canEdit ? <TabsTrigger value="do-not-email">Do Not Email</TabsTrigger> : null}
          {canManage ? <TabsTrigger value="usage">AI Usage</TabsTrigger> : null}
          {canManage ? <TabsTrigger value="audit">Audit Log</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="details">
          <WorkspaceSettingsForm />
        </TabsContent>
        <TabsContent value="members">
          <MembersTable />
        </TabsContent>
        {canManage ? (
          <TabsContent value="invitations">
            <InvitationsTable />
          </TabsContent>
        ) : null}
        {canManage ? (
          <TabsContent value="tools">
            <ToolSettingsPanel />
          </TabsContent>
        ) : null}
        {canManage ? (
          <TabsContent value="classifiers">
            <ClassifiersSettingsPanel />
          </TabsContent>
        ) : null}
        {canEdit ? (
          <TabsContent value="do-not-email">
            <DoNotEmailPanel canRemove={canManage} />
          </TabsContent>
        ) : null}
        {canManage ? (
          <TabsContent value="usage">
            <UsageSettingsPanel />
          </TabsContent>
        ) : null}
        {canManage ? (
          <TabsContent value="audit">
            <AuditSettingsPanel />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  )
}
