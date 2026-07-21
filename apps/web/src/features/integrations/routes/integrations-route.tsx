// apps/web/src/features/integrations/routes/integrations-route.tsx

import { Suspense, useEffect } from "react"
import { getRouteApi, useNavigate } from "@tanstack/react-router"

import { PageHeader } from "@/components/shell/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Skeleton } from "@/components/ui/skeleton"
import { ProviderCatalog } from "@/features/integrations/components/provider-catalog"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

const routeApi = getRouteApi("/app/integrations")

export function IntegrationsRoute() {
  const { workspace } = useActiveWorkspace()
  const navigate = useNavigate()
  const search = routeApi.useSearch()
  const readOnly = workspace.current_user_role === "read_only"

  useEffect(() => {
    if (!search.integration_error && !search.integration_status) {
      return
    }
    void navigate({ replace: true, search: {}, to: "/integrations" })
  }, [navigate, search.integration_error, search.integration_status])

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        description={
          readOnly
            ? "View the accounts and resources available to agents in this workspace."
            : "Connect provider accounts and choose the resources agents can use."
        }
        title="Integrations"
      />
      {search.integration_status === "connected" ? (
        <Alert>
          <AlertTitle>Connection authorized</AlertTitle>
          <AlertDescription>
            We are checking the account and finding the resources available to agents.
          </AlertDescription>
        </Alert>
      ) : null}
      {search.integration_error ? (
        <Alert variant="destructive">
          <AlertTitle>Connection not completed</AlertTitle>
          <AlertDescription>{search.integration_error}</AlertDescription>
        </Alert>
      ) : null}
      <Suspense fallback={<ProviderCatalogSkeleton />}>
        <ProviderCatalog />
      </Suspense>
    </div>
  )
}

function ProviderCatalogSkeleton() {
  return (
    <div className="grid gap-4 xl:grid-cols-2" aria-label="Loading integrations">
      {["provider-one", "provider-two"].map((key) => (
        <div className="flex flex-col gap-4 rounded-xl border p-4" key={key}>
          <Skeleton className="h-5 w-36" />
          <Skeleton className="h-4 w-52" />
          <Skeleton className="h-28 w-full" />
        </div>
      ))}
    </div>
  )
}
