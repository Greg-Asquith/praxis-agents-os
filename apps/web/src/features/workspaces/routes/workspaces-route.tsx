// apps/web/src/features/workspaces/routes/workspaces-route.tsx

import { PageHeader } from "@/components/shell/page-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { CreateWorkspaceDialog } from "@/features/workspaces/components/create-workspace-dialog"
import { WorkspacesTable } from "@/features/workspaces/components/workspaces-table"
import { useWorkspacesQuery } from "@/features/workspaces/api/list-workspaces"
import { pluralize } from "@/lib/format"

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

      <Card>
        <CardHeader>
          <CardTitle>
            {data.total} {pluralize(data.total, "workspace")}
          </CardTitle>
          <CardDescription>
            Workspaces separate access, audit records, and agent configuration.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <WorkspacesTable workspaces={data.workspaces} />
        </CardContent>
      </Card>
    </div>
  )
}
