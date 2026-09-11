// apps/web/src/features/artifacts/routes/artifact-detail-route.tsx

import { useParams, useSearch } from "@tanstack/react-router"
import { useSuspenseQuery } from "@tanstack/react-query"

import { ArtifactDetail } from "@/features/artifacts/components/artifact-detail"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"

export function ArtifactDetailRoute() {
  const { artifactId } = useParams({ from: "/app/artifacts/$artifactId" })
  const search = useSearch({ from: "/app/artifacts/$artifactId" })
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  return (
    <ArtifactDetail
      artifactId={artifactId}
      isSuperAdmin={user.is_super_admin}
      key={artifactId}
      management={search.platform === true && user.is_super_admin}
      openEditor={search.edit === true}
    />
  )
}
