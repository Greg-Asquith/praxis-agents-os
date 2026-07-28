// apps/web/src/features/artifacts/routes/artifact-detail-route.tsx

import { useParams } from "@tanstack/react-router"

import { ArtifactDetail } from "@/features/artifacts/components/artifact-detail"

export function ArtifactDetailRoute() {
  const { artifactId } = useParams({ from: "/app/artifacts/$artifactId" })
  return <ArtifactDetail artifactId={artifactId} key={artifactId} />
}
