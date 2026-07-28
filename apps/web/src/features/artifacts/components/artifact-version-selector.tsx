// apps/web/src/features/artifacts/components/artifact-version-selector.tsx

import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { ArtifactVersion } from "@/features/artifacts/types"

export function ArtifactVersionSelector({
  currentVersionId,
  onValueChange,
  value,
  versions,
}: {
  currentVersionId: string
  onValueChange: (value: string) => void
  value: string
  versions: ArtifactVersion[]
}) {
  return (
    <Select
      value={value}
      onValueChange={(next) => {
        if (next) {
          onValueChange(next)
        }
      }}
    >
      <SelectTrigger aria-label="Artifact version">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {versions.map((version) => (
          <SelectItem key={version.id} value={version.id}>
            <span>Version {String(version.revision_number)}</span>
            {version.id === currentVersionId ? <Badge variant="secondary">Current</Badge> : null}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
