// apps/web/src/features/skills/api/delete-skill.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { skillsQueryKeys } from "@/features/skills/api/list-skills"
import { apiRequest } from "@/lib/api/client"

async function deleteSkill(skillId: string) {
  return apiRequest<undefined>(`/skills/${skillId}`, {
    method: "DELETE",
  })
}

export function useDeleteSkillMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteSkill,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: skillsQueryKeys.workspace() })
    },
  })
}
