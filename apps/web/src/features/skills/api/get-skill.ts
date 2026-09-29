// apps/web/src/features/skills/api/get-skill.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { skillsQueryKeys } from "@/features/skills/api/list-skills"
import type { Skill } from "@/features/skills/types"
import { apiRequest } from "@/lib/api/client"

async function getSkill(skillId: string) {
  return apiRequest<Skill>(`/skills/${skillId}`)
}

function skillQueryOptions(skillId: string) {
  return queryOptions({
    queryKey: skillsQueryKeys.detail(skillId),
    queryFn: () => getSkill(skillId),
    staleTime: 30_000,
  })
}

export function useSkillQuery(skillId: string) {
  return useSuspenseQuery(skillQueryOptions(skillId))
}
