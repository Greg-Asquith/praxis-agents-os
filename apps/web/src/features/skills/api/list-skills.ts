// apps/web/src/features/skills/api/list-skills.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { SkillsListResponse } from "@/features/skills/types"
import { getActiveWorkspaceSlug } from "@/features/workspaces/workspace-context"
import { apiRequest } from "@/lib/api/client"

type ListSkillsParams = {
  includeInactive?: boolean
  limit?: number
  offset?: number
}

export const skillsQueryKeys = {
  all: ["skills"] as const,
  workspace: () => [...skillsQueryKeys.all, activeWorkspaceQueryScope()] as const,
  details: () => [...skillsQueryKeys.workspace(), "detail"] as const,
  detail: (skillId: string) => [...skillsQueryKeys.details(), skillId] as const,
  documents: (skillId: string) => [...skillsQueryKeys.detail(skillId), "documents"] as const,
  lists: () => [...skillsQueryKeys.workspace(), "list"] as const,
  list: (params: ListSkillsParams = {}) => [...skillsQueryKeys.lists(), params] as const,
}

function activeWorkspaceQueryScope() {
  return getActiveWorkspaceSlug() ?? "__no_workspace__"
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
