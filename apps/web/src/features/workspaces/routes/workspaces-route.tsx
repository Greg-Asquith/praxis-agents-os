// apps/web/src/features/workspaces/routes/workspaces-route.tsx

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { CreateWorkspaceDialog } from "@/features/workspaces/components/create-workspace-dialog"
import { WorkspacesTable } from "@/features/workspaces/components/workspaces-table"
import { useWorkspacesQuery } from "@/features/workspaces/api/list-workspaces"
import { pluralize } from "@/lib/format"

export function WorkspacesRoute() {
  const { data } = useWorkspacesQuery()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex flex-col gap-2">
          <p className="text-muted-foreground text-sm font-medium">Workspace access</p>
          <h1 className="font-heading text-2xl font-semibold tracking-normal">Workspaces</h1>
        </div>
        <CreateWorkspaceDialog />
      </div>

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
