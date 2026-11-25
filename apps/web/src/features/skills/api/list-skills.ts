// apps/web/src/features/skills/api/list-skills.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { SkillsListResponse } from "@/features/skills/types"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"
import { apiRequest } from "@/lib/api/client"

type ListSkillsParams = {
  includeInactive?: boolean
  limit?: number
  offset?: number
  search?: string
}

const baseSkillsQueryKeys = createWorkspaceScopedQueryKeys("skills")

export const skillsQueryKeys = {
  ...baseSkillsQueryKeys,
  documents: (skillId: string) => [...baseSkillsQueryKeys.detail(skillId), "documents"] as const,
  documentMarkdown: (skillId: string, documentName: string) =>
    [...baseSkillsQueryKeys.detail(skillId), "documents", documentName, "markdown"] as const,
}

export function skillMutationQueryKey(scope: "workspace" | "platform") {
  return scope === "platform" ? skillsQueryKeys.all : skillsQueryKeys.workspace()
}

async function listSkills({
  includeInactive = false,
  limit = 100,
  offset = 0,
  search,
}: ListSkillsParams = {}) {
  return apiRequest<SkillsListResponse>("/skills/", {
    query: {
      include_inactive: includeInactive,
      limit,
      offset,
      ...(search ? { search } : {}),
    },
  })
}

function skillsQueryOptions(params: ListSkillsParams = {}) {
  return queryOptions({
    queryKey: skillsQueryKeys.list(params),
    queryFn: () => listSkills(params),
    staleTime: 30_000,
  })
}

export function useSkillsQuery(params: ListSkillsParams = {}) {
  return useSuspenseQuery(skillsQueryOptions(params))
}
