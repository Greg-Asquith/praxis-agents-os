// apps/web/src/features/artifacts/format.ts

import type { ArtifactType } from "@/features/artifacts/types"

export function artifactTypeLabel(type: ArtifactType) {
  if (type === "html") return "HTML"
  if (type === "csv") return "CSV"
  if (type === "image-ref") return "Image"
  return type === "mermaid" ? "Mermaid" : "Markdown"
}
