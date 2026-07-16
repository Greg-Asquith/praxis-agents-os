// apps/web/src/features/skills/api/get-skill-document-markdown.ts

import { queryOptions } from "@tanstack/react-query"

import { skillsQueryKeys } from "@/features/skills/api/list-skills"
import type { SkillDocumentMarkdownResponse } from "@/features/skills/types"
import { apiRequest } from "@/lib/api/client"

export function skillDocumentMarkdownQueryOptions(skillId: string, documentName: string) {
  return queryOptions({
    queryKey: skillsQueryKeys.documentMarkdown(skillId, documentName),
    queryFn: () =>
      apiRequest<SkillDocumentMarkdownResponse>(
        `/skills/${skillId}/documents/${documentName}/markdown`
      ),
    staleTime: 30_000,
  })
}
