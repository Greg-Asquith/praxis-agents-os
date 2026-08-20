// apps/web/src/features/memories/api/delete-memory.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { memoriesQueryKeys } from "@/features/memories/api/list-memories"
import { apiRequestNoContent } from "@/lib/api/client"

type DeleteMemoryInput = {
  memoryId: string
  purge: boolean
}

export function useDeleteMemoryMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ memoryId, purge }: DeleteMemoryInput) =>
      apiRequestNoContent(`/memories/${memoryId}`, {
        method: "DELETE",
        query: { purge },
      }),
    onSuccess: async (_data, input) => {
      queryClient.removeQueries({ queryKey: memoriesQueryKeys.detail(input.memoryId) })
      await queryClient.invalidateQueries({ queryKey: memoriesQueryKeys.workspace() })
    },
  })
}
