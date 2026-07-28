// apps/web/src/features/artifacts/routes/artifacts-route.tsx

import { PageHeader } from "@/components/shell/page-header"
import { useArtifactsQuery } from "@/features/artifacts/api/list-artifacts"
import { ArtifactsTable } from "@/features/artifacts/components/artifacts-table"

export function ArtifactsRoute() {
  const { data } = useArtifactsQuery()
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        description="Preview, revise, restore, and share durable work created by your agents."
        title="Artifacts"
      />
      <ArtifactsTable artifacts={data.items} />
    </div>
  )
}
