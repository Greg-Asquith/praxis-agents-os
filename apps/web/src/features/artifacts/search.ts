// apps/web/src/features/artifacts/search.ts

import type { ArtifactSortField } from "@/features/artifacts/types"
import { validateListSearch, type ListSearch } from "@/lib/list-search"

export const ARTIFACT_SORT_FIELDS = new Set<ArtifactSortField>([
  "artifact_type",
  "title",
  "updated_at",
  "version_count",
])

export type ArtifactsSearch = ListSearch<ArtifactSortField>

export type ArtifactDetailSearch = {
  edit?: true
  platform?: true
}

export function validateArtifactsSearch(search: Record<string, unknown>): ArtifactsSearch {
  return validateListSearch(search, ARTIFACT_SORT_FIELDS)
}

export function validateArtifactDetailSearch(
  search: Record<string, unknown>
): ArtifactDetailSearch {
  return {
    ...(search["edit"] === true ? { edit: true } : {}),
    ...(search["platform"] === true ? { platform: true } : {}),
  }
}
