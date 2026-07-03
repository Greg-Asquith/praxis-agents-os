// apps/web/src/features/skills/api/update-skill.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { skillsQueryKeys } from "@/features/skills/api/list-skills"
import type { Skill, SkillUpdateRequest } from "@/features/skills/types"
import { apiRequest } from "@/lib/api/client"

type UpdateSkillInput = {
  payload: SkillUpdateRequest
  skillId: string
}

async function updateSkill({ payload, skillId }: UpdateSkillInput) {
  return apiRequest<Skill>(`/skills/${skillId}`, {
    body: payload,
    method: "PATCH",
  })
}

export function useUpdateSkillMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateSkill,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: skillsQueryKeys.all })
    },
  })
}
