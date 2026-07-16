// apps/web/src/features/workspaces/routes/workspaces-route.tsx

import { PageHeader } from "@/components/shell/page-header"
import { CreateWorkspaceDialog } from "@/features/workspaces/components/create-workspace-dialog"
import { WorkspacesTable } from "@/features/workspaces/components/workspaces-table"
import { useWorkspacesQuery } from "@/features/workspaces/api/list-workspaces"

export function WorkspacesRoute() {
  const { data } = useWorkspacesQuery()
  const hasWorkspaces = data.workspaces.length > 0

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={hasWorkspaces ? <CreateWorkspaceDialog /> : null}
        description="Separate access, audit records, and agent configuration."
        title="Workspaces"
      />

      <WorkspacesTable workspaces={data.workspaces} />
    </div>
  )
}
