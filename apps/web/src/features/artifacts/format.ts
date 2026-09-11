// apps/web/src/features/artifacts/format.ts

import type { ArtifactSummary, ArtifactType } from "@/features/artifacts/types"
import { ApiError, getErrorMessage } from "@/lib/api/errors"

export function artifactTypeLabel(type: ArtifactType) {
  if (type === "html") return "HTML"
  if (type === "csv") return "CSV"
  if (type === "image-ref") return "Image"
  return type === "mermaid" ? "Mermaid" : "Markdown"
}

// Platform saves carry the reviewed version; the API answers a stale review with a conflict.
export function isStaleArtifactError(error: unknown) {
  return error instanceof ApiError && error.status === 409
}

export function describeArtifactSaveError(error: unknown) {
  return isStaleArtifactError(error)
    ? "This artifact changed since you opened it. Review the latest version, then try again."
    : getErrorMessage(error)
}

export type ArtifactBadgeSource = Pick<ArtifactSummary, "scope" | "is_published"> & {
  published_version_id?: string | null
}

// Only management reads include unpublished rows; tenant reads never reach the second branch.
export function publicationLabel(artifact: ArtifactBadgeSource) {
  if (artifact.scope !== "platform" || artifact.is_published) return null
  return artifact.published_version_id ? "Withdrawn" : "Unpublished"
}
