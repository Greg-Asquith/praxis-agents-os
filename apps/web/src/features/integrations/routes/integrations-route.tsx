// apps/web/src/features/integrations/routes/integrations-route.tsx

import { Suspense } from "react"
import { Link } from "@tanstack/react-router"
import { Layers3Icon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ProviderList } from "@/features/integrations/components/provider-list"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

export function IntegrationsRoute() {
  const { workspace } = useActiveWorkspace()
  const readOnly = workspace.current_user_role === "read_only"

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={
          <Button variant="outline" render={<Link to="/integrations/context-groups" />}>
            <Layers3Icon data-icon="inline-start" />
            Context Groups
          </Button>
        }
        description={
          readOnly
            ? "View the accounts and resources available to agents in this workspace."
            : "Connect provider accounts and choose the resources agents can use."
        }
        title="Integrations"
      />
      <Suspense fallback={<ProviderCatalogSkeleton />}>
        <ProviderList />
      </Suspense>
    </div>
  )
}

function ProviderCatalogSkeleton() {
  return (
    <div className="divide-border divide-y" aria-label="Loading integrations">
      {["provider-one", "provider-two", "provider-three"].map((key) => (
        <div className="flex min-h-20 items-center gap-4 px-3 py-4" key={key}>
          <Skeleton className="size-10 rounded-xl" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-64 max-w-full" />
          </div>
          <Skeleton className="h-5 w-28 rounded-full" />
        </div>
      ))}
    </div>
  )
}
