// apps/web/src/features/artifacts/components/artifact-badges.tsx

import { Badge } from "@/components/ui/badge"
import { publicationLabel, type ArtifactBadgeSource } from "@/features/artifacts/format"

export function ArtifactBadges({ artifact }: { artifact: ArtifactBadgeSource }) {
  if (artifact.scope !== "platform") return null
  const publication = publicationLabel(artifact)
  return (
    <>
      <Badge variant="secondary">Shared</Badge>
      {publication ? <Badge variant="outline">{publication}</Badge> : null}
    </>
  )
}
