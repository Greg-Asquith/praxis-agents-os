// apps/web/src/features/skills/api/delete-skill.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { skillMutationQueryKey } from "@/features/skills/api/list-skills"
import type { Skill } from "@/features/skills/types"
import { apiRequestNoContent } from "@/lib/api/client"

type DeleteSkillInput = Pick<Skill, "id" | "scope">

async function deleteSkill({ id }: DeleteSkillInput) {
  return apiRequestNoContent(`/skills/${id}`, {
    method: "DELETE",
  })
}

export function useDeleteSkillMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteSkill,
    onSuccess: async (_result, skill) => {
      await queryClient.invalidateQueries({ queryKey: skillMutationQueryKey(skill.scope) })
    },
  })
}
