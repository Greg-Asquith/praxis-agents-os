// apps/web/src/features/skills/api/list-skills.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { SkillsListResponse } from "@/features/skills/types"
import { createWorkspaceScopedQueryKeys } from "@/features/workspaces/query-keys"
import { apiRequest } from "@/lib/api/client"

type ListSkillsParams = {
  includeInactive?: boolean
  limit?: number
  offset?: number
}

const baseSkillsQueryKeys = createWorkspaceScopedQueryKeys("skills")

export const skillsQueryKeys = {
  ...baseSkillsQueryKeys,
  documents: (skillId: string) => [...baseSkillsQueryKeys.detail(skillId), "documents"] as const,
}

async function listSkills({
  includeInactive = false,
  limit = 100,
  offset = 0,
}: ListSkillsParams = {}) {
  return apiRequest<SkillsListResponse>("/skills/", {
    query: {
      include_inactive: includeInactive,
      limit,
      offset,
    },
  })
}

export function skillsQueryOptions(params: ListSkillsParams = {}) {
  return queryOptions({
    queryKey: skillsQueryKeys.list(params),
    queryFn: () => listSkills(params),
    staleTime: 30_000,
  })
}

export function useSkillsQuery(params: ListSkillsParams = {}) {
  return useSuspenseQuery(skillsQueryOptions(params))
}
