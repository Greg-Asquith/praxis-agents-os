// apps/web/src/features/skills/api/create-skill.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { skillsQueryKeys } from "@/features/skills/api/list-skills"
import type { Skill, SkillCreateRequest } from "@/features/skills/types"
import { apiRequest } from "@/lib/api/client"

async function createSkill(payload: SkillCreateRequest) {
  return apiRequest<Skill>("/skills/", {
    body: payload,
    method: "POST",
  })
}

export function useCreateSkillMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createSkill,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: skillsQueryKeys.lists() })
    },
  })
}
